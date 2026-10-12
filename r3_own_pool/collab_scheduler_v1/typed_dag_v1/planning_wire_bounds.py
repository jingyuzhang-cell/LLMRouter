"""Opt-in protocol proposal. Limits strings; never truncates candidates or infers links."""
import copy
VERSION='bounded-planning-wire.v1'
LIMITS={'ref':48,'node_ref':48,'symbol':48,'unit':24,'name':80,'description':240,'subtask':240}

def bounded_schema(schema,max_nodes=5):
 out=copy.deepcopy(schema)
 def walk(node,field=None):
  if not isinstance(node,dict):return
  if node.get('type')=='array':node['maxItems']=min(node.get('maxItems',max_nodes),max_nodes)
  if node.get('type')=='string' and field in LIMITS:
   node['maxLength']=min(node.get('maxLength',LIMITS[field]),LIMITS[field])
  for key,value in node.items():
   if key=='properties':
    for name,item in value.items():walk(item,name)
   elif key=='input_producers':pass
   elif key=='items':walk(value,field)
   elif isinstance(value,dict):walk(value,field)
   elif isinstance(value,list):
    for item in value:walk(item,field)
  # Producer reference arrays carry their semantic field in a parent object.
  props=node.get('properties',{})
  if 'input_producers' in props:
   for arr in props['input_producers'].get('properties',{}).values():
    arr['items']['maxLength']=LIMITS['ref']
 walk(out)
 return out
