import unittest
from .tool_aware_v1 import calculate,parse_facts,context
class Tests(unittest.TestCase):
 def test_arithmetic(self):
  f={'facts':[{'value':1733},{'value':1912}]}
  self.assertAlmostEqual(calculate('v0*(1+(v0-v1)/v1)',f),1570.7578451882845)
 def test_reject_code(self):
  for expr in ['__import__("os").system("id")','v0**100','[v0][0]','v0.__class__','v999','2*v0','1/0']:
   with self.assertRaises(Exception):calculate(expr,{'facts':[{'value':7}]})
 def test_extract_schema(self):
  with self.assertRaises(Exception):parse_facts('{"facts":[]}')
  with self.assertRaises(Exception):parse_facts('{"facts":[{"value":true,"evidence":"x"}]}')
 def test_no_labels_in_context(self):
  x={'paragraphs':['public paragraph'],'tables':['<table><tr><td>17</td></tr></table>'],'qa':{'answer':'SECRET','program':'SECRET'},'table_description':['SECRET']}
  text=context(x);self.assertNotIn('SECRET',text);self.assertIn('17',text)
if __name__=='__main__':unittest.main()
