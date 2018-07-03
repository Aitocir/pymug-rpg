#  main server file

import socket
import ssl
import sys
import queue
import rethinkdb as r

from .server.transport.courier_in import *
from .server.transport.courier_out import *
from .server.transport.socket_in import recv_socket
from .server.transport.socket_out import send_socket

from .server.storage.login import LoginDAO
from .server.storage.game import GameDAO

from .server.game.input import process_typed_input
from .server.game.system_commands import system_cmds
from .server.game.ecs_system import *

from .common import messages as messenger

class PymugServer:
    def __init__(self, certfile, keyfile):
        self._cert = certfile
        self._key = keyfile
        self._gamethreads = 5
        self._host = ''
        self._port = 29999
        self._db_host = 'localhost'
        self._db_port = 28015
        self._connbuffer = 5
        self._usercmds = {}
        self._syscmds = system_cmds()
        self._c = None
        self._clock_systems = {}
        self._timer_systems = {}
    
    #
    #  server property setters
    #
    
    def set_server_host(self, host):
        if isinstance(host, str):
            self._host = host
    def set_server_port(self, port):
        if isinstance(port, int):
            self._port = port
    def set_db_host(self, host):
        if isinstance(host, str):
            self._db_host = host
    def set_db_port(self, port):
        if isinstance(port, int):
            self._db_port = port
    def set_game_thread_count(self, count):
        if isinstance(count, int):
            self._gamethreads = max(1, count)
    def set_connection_buffer(self, buff_len):
        if isinstance(buff_len, int):
            self._connbuffer = max(0, buff_len)
    
    #
    #  command registration
    #
    
    def register_player_command(self, cmd, gamefunc):
        if isinstance(cmd, str) and callable(gamefunc):
            self._usercmds[cmd] = gamefunc
        else:
            raise ValueError('cmd must be a string, and gamefunc must be a function')
    
    def override_system_command(self, cmd, gamefunc):
        if isinstance(cmd, str) and callable(gamefunc):
            if cmd in self._syscmds:
                self._syscmds[cmd] = gamefunc
            else:
                raise ValueError('"{0}" is not a recognized system command'.format(cmd))
        else:
            raise ValueError('cmd must be a string, and gamefunc must be a function')
    
    #
    #  allows callers to define ECS System that processes matching Components in real time
    #  component predicate is a list of 3-tuple conditions to filter Components by
    #  must take the form (row_name, comparison_op, value)
    def define_ecs_clock_system(self, system_name, component_name, system_func, component_predicates=[], update_seconds=60.0, tick_seconds=None):
        if not isinstance(system_name, str):
            raise ValueError('define_ecs_system: system_name must be a string')
        if not isinstance(component_name, str):
            raise ValueError('define_ecs_system: component_name must be a string')
        if not isinstance(component_predicates, list):
            raise ValueError('define_ecs_system: component_name must be a list of 3-tuple predicates')
        if not callable(system_func):
            raise ValueError('define_ecs_system: system_func must be a function')
        if not isinstance(update_seconds, int) and not isinstance(update_seconds, float):
            raise ValueError('define_ecs_system: update_seconds must be an int or float')
        if not isinstance(tick_seconds, int) and not isinstance(tick_seconds, float):
            raise ValueError('define_ecs_system: tick_seconds must be an int or float')
        if tick_seconds == None:
            tick_seconds = update_seconds / 10
        self._clock_systems[system_name] = (system_func, component_name, component_predicates, update_seconds, tick_seconds)
    
    #
    #  allows callers to define ECS System that executes on a regular interval
    def define_ecs_timer_system(self, system_name, system_func, update_seconds=60.0):
        if not isinstance(system_name, str):
            raise ValueError('define_ecs_system: system_name must be a string')
        if not callable(system_func):
            raise ValueError('define_ecs_system: system_func must be a function')
        if not isinstance(update_seconds, int) and not isinstance(update_seconds, float):
            raise ValueError('define_ecs_system: update_seconds must be an int or float')
        self._timer_systems[system_name] = (system_func, update_seconds)
    
    #  TODO: make another System type that runs event-driven based on changes to matching Components
    #def define_ecs_event_system(self, system_name, component_name, system_func, <predicates and any other needed info for processing filter>)
        
    #
    #  magick time
    #
    
    def init_db(self, components=[]):
        self._c = r.connect(self._db_host, self._db_port)
        
        dbs = r.db_list().run(self._c)
        if 'login' not in dbs:
            r.db_create('login').run(self._c)
            r.db('login').table_create('registrations', primary_key='username').run(self._c)
        if 'components' not in dbs:
            r.db_create('components').run(self._c)
        
        db_comps = set(r.db('components').table_list().run(self._c))
        components.extend(['inventory', 'skills'])  #  TODO: add any component tables defined by default by pymug-rpg the designer gets for free
        for x in set(components).difference(db_comps):
            r.db('components').table_create(x, primary_key='entity').run(self._c)
        
        if 'definitions' not in dbs:
            r.db_create('definitions').run(self._c)
        db_defs = set(r.db('definitions').table_list().run(self._c))
        if 'itembases' not in db_defs:
            r.db('definitions').table_create('itembases', primary_key='name').run(self._c)
        if 'itemmodifiers' not in db_defs:
            r.db('definitions').table_create('itemmodifiers', primary_key='id').run(self._c)
            r.db('definitions').table('itemadjectives').index_create('name').run(conn)
        if 'recipes' not in db_defs:
            r.db('definitions').table_create('recipes', primary_key='name').run(self._c)
            r.db('definitions').table('recipes').index_create('tool').run(conn)
    
    def load_item_bases_from_string(self, items_str):
        try:
            items = json.loads(items_str)
            r.db('definitions').table('itembases').insert(items).run(self._c)
        except:
            #  TODO: differentiate between JSON format and db write exceptions
            raise ValueError('Invalid JSON provided for item bases')
    
    def load_item_bases_from_file(self, items_file):
        try:
            with open(items_file, 'r') as f:
                self.load_item_bases_from_string(f.read())
        except:
            #  TODO: differentiate between JSON format and file IO exceptions
            raise ValueError('File {0} contains invalid item base JSON'.format(items_file))
    
    def load_item_bases_from_dir(self, items_dir, recursive=False):
        files = [os.path.join(items_dir, x) for x in os.listdir(items_dir) if os.path.isfile(os.path.join(items_dir, x))]
        for f in files:
            self.load_item_bases_from_file(f)
        if recursive:
            dirs = [os.path.join(items_dir, x) for x in os.listdir(items_dir) if os.path.isdir(os.path.join(items_dir, x))]
            for d in dirs:
                self.load_item_bases_from_dir(d, True)
    
    def load_item_modifiers_from_string(self, items_str):
        try:
            items = json.loads(items_str)
            r.db('definitions').table('itemmodifiers').insert(items).run(self._c)
        except:
            #  TODO: differentiate between JSON format and db write exceptions
            raise ValueError('Invalid JSON provided for item modifiers')
    
    def load_item_modifiers_from_file(self, items_file):
        try:
            with open(items_file, 'r') as f:
                self.load_item_modifiers_from_string(f.read())
        except:
            #  TODO: differentiate between JSON format and file IO exceptions
            raise ValueError('File {0} contains invalid item modifier JSON'.format(items_file))
    
    def load_item_modifiers_from_dir(self, items_dir, recursive=False):
        files = [os.path.join(items_dir, x) for x in os.listdir(items_dir) if os.path.isfile(os.path.join(items_dir, x))]
        for f in files:
            self.load_item_modifiers_from_file(f)
        if recursive:
            dirs = [os.path.join(items_dir, x) for x in os.listdir(items_dir) if os.path.isdir(os.path.join(items_dir, x))]
            for d in dirs:
                self.load_item_modifiers_from_dir(d, True)
    
    def load_recipes_from_string(self, items_str):
        try:
            recipes = []
            bad_recipe_count = 0
            recipe_defs = json.loads(items_str)
            for r in recipe_defs:
                recipe = {}
                recipe['itemrefs'] = [x[0] for x in ingredients]
                recipe['constants'] = r['specific-ingredients'] if 'specific-ingredients' in r else {}
                recipe['variables'] = r['typed-ingredients'] if 'typed-ingredients' in r else {}
                recipe['tool'] = r['tool'] if 'tool' in r else '' 
                if recipe['constants']=={} and recipe['variables']=={} and recipe['tool']=='':
                    bad_recipe_count += 1
                    continue
                recipe['success'] = r['success'] if 'success' in r else {}
                recipe['failure'] = r['failure'] if 'failure' in r else {}
                recipe['success_xp'] = r['success_xp'] if 'success_xp' in r else {}
                recipe['failure_xp'] = r['failure_xp'] if 'failure_xp' in r else {}
                recipe['random'] = r['random'] if 'random' in r and 0.0<r['random']<1.0 else 1.0
                if 'skill' not in r:
                    recipe['skill_name'] = ''
                else:
                    try:
                        recipe['skill_name'] = r['skill']['name']
                        base = (r['skill']['first_level'] if 'min' in r['skill'] else 0) - 1
                        mastery = r['skill']['mastery_level'] if 'mastery' in r['skill'] else base+1
                        recipe['skill_base'] = base
                        recipe['skill_steps'] = mastery - base
                        recipe['skill_curve'] = r['skill']['difficulty'] if 'curve' in r['skill'] else 1.0
                    except:
                        bad_recipe_count += 1
                        continue
                recipes.append(recipe)
            if bad_recipe_count:
                print('Failed to load {0} out of {1} recipes because of missing values'.format(bad_recipe_count, bad_recipe_count+len(recipes)))
            r.db('definitions').table('recipes').insert(recipes).run(self._c)
        except:
            #  TODO: differentiate between JSON format and db write exceptions
            raise ValueError('Invalid JSON provided for recipes')
    
    def load_recipes_from_file(self, items_file):
        try:
            with open(items_file, 'r') as f:
                self.load_recipes_from_string(f.read())
        except:
            #  TODO: differentiate between JSON format and file IO exceptions
            raise ValueError('File {0} contains invalid recipe JSON'.format(items_file))
    
    def load_recipes_from_dir(self, items_dir, recursive=False):
        files = [os.path.join(items_dir, x) for x in os.listdir(items_dir) if os.path.isfile(os.path.join(items_dir, x))]
        for f in files:
            self.load_recipes_from_file(f)
        if recursive:
            dirs = [os.path.join(items_dir, x) for x in os.listdir(items_dir) if os.path.isdir(os.path.join(items_dir, x))]
            for d in dirs:
                self.load_recipes_from_dir(d, True)

    """
    def add_to_db(self, db, table, obj):
        #  This function will not overwrite existing data
        r.db(db).table(table).insert(obj, conflict=lambda id, old_doc, newdoc: old_doc).run(self._c)
    """
    
    def run(self, debug=False):
        if self._c != None:
            self._c.close()
        
        #
        #  define queues
        q_courier_in = queue.Queue()
        q_gamethread = queue.Queue()
        q_courier_out = queue.Queue()
        
        #
        #  setup architecture
        logindao = LoginDAO(self._db_host, self._db_port, 'login')
        courier_in = CourierInbound(q_courier_in, q_courier_out, q_gamethread, logindao, messenger)
        courier_out = CourierOutbound(q_courier_out, messenger)
        courier_in.run()
        courier_out.run()
        #  input processing threads (caller set, >= 1)
        for _ in range(self._gamethreads):
            start_new_thread(process_typed_input, (q_gamethread, q_courier_out, self._usercmds, self._syscmds, GameDAO(), messenger))
        #  ECS system processing threads (1 per system)
        for system in self._clock_systems:
            start_new_thread(ecs_clock_system_thread, (GameDAO(), q_courier_out, messenger, system, *self._clock_systems[system]))
        for system in self._timer_systems:
            start_new_thread(ecs_timer_system_thread, (GameDAO(), q_courier_out, messenger, system, *self._timer_systems[system]))
        
        #
        #  connection loop
        sock = socket.socket()
        s = ssl.wrap_socket(sock, server_side=True, ssl_version=ssl.PROTOCOL_TLSv1_2, certfile=self._cert, keyfile=self._key)
        s.bind((self._host, self._port))
        s.listen(self._connbuffer)
        
        print('Server ready!')
        while True:
            conn, addr = s.accept()
            address = '__'.join([str(x) for x in addr])
            if debug:
                print('Got connection from: {0}'.format(address))
            q_socket_out = queue.Queue()
            start_new_thread(recv_socket, (conn, q_courier_in, address,))
            start_new_thread(send_socket, (conn, q_socket_out,))
            q_courier_in.put((1, address))
            q_courier_out.put((1, address, q_socket_out))
    
if __name__ == "__main__":
    if len(sys.argv)<3:
        print('must provide public cert and key files on command line to run gameserver.py directly')
        exit()
    server = PymugServer(sys.argv[1], sys.argv[2])
    server.run()