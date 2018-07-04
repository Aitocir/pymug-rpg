#  user command definitions
#  all functions should return lists of messages

#
#  Crafting
#

def _validate_crafting(username, db, recipe_name, item_refs):
    recipe = {}   #  TODO: add function to db that will look up recipe definition 
    #
    #  1) check tool
    #  TODO: check if player inventory has recipe['tool'] in the wield slot
    #        if not, return False, 'not wielding {0}'.format(recipe['tool'])
    
    #
    #  2) check skill minimum level
    #  TODO: check if len(recipe['skill_name']) and player.skills.<recipe['skill_name']> > recipe['skill_base']
    #        if not, return False, 'not high enough level in {0}'.format(recipe['skill_name'])
    
    #
    #  3) check ingredients
    ingredients = {}
    item_names = set(item_refs)
    for thing in recipe['specific-ingredients']:
        if thing not in item_names:
            return False, 'missing {0}'.format(thing), {}
        ingredients[thing] = recipe['specific-ingredients'][thing]
        item_names.remove(thing)
    variables = {}
    for thing in recipe['typed-ingredients']:
        variables[thing] = None
    for thing in item_names:
        item = {}  #  TODO: add function to db that will look up item definitions
        if item['type'] in variables and variables[item['type']] != None:
            return False, 'ambiguous ingredients "{0}" and "{1}"'.format(item['name'], variables[item['type']]), {}
        elif item['type'] in variables:
            variables[item['type']] = item['name']
    for var in variables:
        if variables[var] == None:
            return False, 'missing "{0}"'.format(var), {}
        ingredients[variables[var]] = recipe['typed-ingredients'][var]
    #  TODO: check that ingredients dicitonary are a subset of the player's inventory
    #  if not, return False, "you don't have enough items to craft"
    return True, '', ingredients
    
def _craftfortool(username, db, messenger, payload):
    tool_name = payload.strip()
    #  TODO: check for the existence of tool name
    #  TODO: look up recipes that require tool
    return []

def _checkcraft(username, db, messenger, payload):
    error_json = {'cmd': '_checkcraft'}
    terms = payload.strip().split('#')
    if len(terms) != 2:
        return [messenger.error_json({'cmd': '_checkcraft', 'message': 'malformed parameters'}, username)]
    recipe_name = terms[0].strip()
    
    item_refs = [x.strip() for x in terms[1].strip().split(';')]
    can_craft, message, cost_items = _validate_crafting(username, db, recipe_name, item_refs)
    return [messenger.plain_json({'type': 'crafting', 'craft_config': payload, 'craftable': can_craft, 'message': message}, username)]

def _craft(username, db, messenger, payload):
    #  Craft items into other items
    #  Params:
    #      name of recipe to craft
    #      list of items and counts in the order of consumption
    terms = payload.strip().split('#')
    if len(terms) != 2:
        return [messenger.plain_text('ERR:_craft:bad params', username)]
    recipe_name = terms[0].strip()
    
    item_refs = [x.strip() for x in terms[1].strip().split(';')]
    can_craft, message, cost_items = _validate_crafting(username, db, recipe_name, item_refs)
    if not can_craft:
        return [messenger.plain_json({'type': 'crafting', 'craft_config': payload, 'craftable': can_craft, 'message': message}, username)]
    
    #  TODO: run the skill chance algorithm to see success or failure
    
    #  TODO: run the random chance algorithm if skill chance succeeds
    
    #  TODO: make the player inventory changes for crafting success or failure
    
    #  TODO: re-check the validity of the crafting so that can_craft can be False if this crafting cannot be repeated
    
    return [messenger.plain_json({'type': 'inventory', 'subtract': cost_items, 'add': {}}, username),  #  TODO: set add equal to the crafting results
        messenger.plain_json({'type': 'crafting', 'craft_config': payload, 'craftable': can_craft, 'message': message}, username)]

def rpg_cmds():
    return {
        '_craftfortool', _craftfortool,  #  get recipe names for a given tool (that are known by player)
        '_checkcraft': _checkcraft,      #  see if provided items will craft provided recipe
        '_craft': _craft,                #  craft items from other items
    }