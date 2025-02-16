from lxml import etree
import numpy as np

import py_trees.decorators
import py_trees.display

from pyeda.inter import *
from pyeda.boolalg.expr import _LITS

import pipeline_constants as constants

AND = "and"
OR = "or"

# [[  0.   0. 194.   0.   0.   0.]] -> 2
def find_max_index(numpy_1D_array):
	max_element = np.amax(numpy_1D_array)
	index = np.where(numpy_1D_array == max_element)
	return index[1][0]

def add_to_dict(dictionary, key, value):
	if not key in dictionary:
		dictionary[key] = value
	else:
		dictionary[key] = dictionary[key] + " | " + value

def invert_expression(exp):
	if ">=" in exp:
		return exp.replace(">=", "<")
	elif "<=" in exp:
		return exp.replace("<=", ">")
	elif ">" in exp:
		return exp.replace(">", "<=")
	elif "<" in exp:
		return exp.replace("<", ">=")
	elif "True" in exp:
		return exp.replace("True", "False")
	elif "False" in exp:
		return exp.replace("False", "True")
	else: return exp

def is_leaf_node(dt, node_index):
	return (dt.children_left[node_index] == -1 and dt.children_right[node_index] == -1)

def get_key(dictionary, val):
    for key, value in dictionary.items():
         if val == value:
             return key
 
    return "key doesn't exist"

#in order traversal
def dt_to_pstring_recursive(dt, node_index, current_letter, current_pstring, sym_lookup, action_to_pstring, feature_names, label_names):
	if is_leaf_node(dt, node_index):
		# dt.value[node_index]: [[  0.   0. 194.   0.   0.   0.]] -> action = 'Dialogue: 3'
		action = str(label_names[find_max_index(dt.value[node_index])])
		add_to_dict(action_to_pstring, action, current_pstring)
		return current_letter
	else:
		true_rule = None
		if "_" in feature_names[dt.feature[node_index]]:
			true_rule = feature_names[dt.feature[node_index]] + " == False"
		else:
			true_rule = feature_names[dt.feature[node_index]] + " <= " + str(round(dt.threshold[node_index], 3))
		false_rule = invert_expression(true_rule)

		true_letter = None
		false_letter = None

		if (not true_rule in sym_lookup) and (not false_rule in sym_lookup):
			add_to_dict(sym_lookup, true_rule, current_letter)
			current_letter = chr(ord(current_letter) + 1)

		if true_rule in sym_lookup:
			true_letter = sym_lookup.get(true_rule)
			false_letter = "~" + true_letter

		left_pstring = true_letter if current_pstring == "" else current_pstring + " & " + true_letter
		right_pstring = false_letter if current_pstring == "" else current_pstring + " & " + false_letter
		# traverse left side of tree (true condition)
		current_letter = dt_to_pstring_recursive(dt, \
												dt.children_left[node_index], \
												current_letter, \
												left_pstring, \
												sym_lookup, \
												action_to_pstring, \
												feature_names, \
												label_names)

		# traverse right side of tree (false condition)
		current_letter = dt_to_pstring_recursive(dt, \
												dt.children_right[node_index], \
												current_letter, \
												right_pstring, \
												sym_lookup, \
												action_to_pstring, \
												feature_names, \
												label_names)
		return current_letter

# sym_lookup format:
# {'tsla <= 19.14': 'a', 
#  'exerciseSubmissionResult_Correct == False': 'b', 
#  'exerciseSubmissionResult_No Entry == False': 'c', 
#  'ScaffLeft <= 0.5': 'd', ...}

# action_to_pstring:
# {'Dialogue: 3': 'a & b & c & d & e', 
#  'PPA': 'a & b & c & d & ~e | ~a & h & i & ~j | ~a & ~h', 
#  'Dialogue: 4': 'a & b & c & ~d | a & b & ~c & f & ~g', 
#  'Dialogue: 1': 'a & b & ~c & f & g | a & b & ~c & ~f', ...}

def dt_to_pstring(dt, feature_names, label_names):
	sym_lookup = {}
	action_to_pstring = {}
	dt_to_pstring_recursive(dt, 0, 'a', "", sym_lookup, action_to_pstring, feature_names, label_names)
	return sym_lookup, action_to_pstring

def get_common_conditions(condition_pstring):
	if condition_pstring.to_ast()[0] == OR:
		all_condition_sets = []
		for operand in condition_pstring.to_ast()[1:]:
			list_conditions = [condition[1] for condition in operand[1:]]
			all_condition_sets.append(list_conditions)
		return list(set.intersection(*map(set, all_condition_sets))), all_condition_sets
	else:
		return [],[]

def int_to_condition(int_condition):
	return str(_LITS[int_condition])

def factorize_pstring(pstring_dict):
	for action, condition_pstring in pstring_dict.items():
		can_simplify = condition_pstring.to_ast()[0] == OR
		conditions_in_all, all_condition_sets = get_common_conditions(condition_pstring)
		if can_simplify and conditions_in_all:
			new_pstring = "("
			for common_condition in conditions_in_all:
				new_pstring += str(_LITS[common_condition]) + " & "
				[condition_set.remove(common_condition) for condition_set in all_condition_sets]

			# [[3, -4], [-3, 9, -10]] -> [['c', '~d'], ['~c', 'f', '~g']]
			all_condition_sets_char = [list(map(int_to_condition, condition_set)) for condition_set in all_condition_sets]

			# [['c', '~d'], ['~c', 'f', '~g']] -> ((c & ~d) | (~c & f & ~g))
			ors = str(all_condition_sets_char).replace(',', ' &')\
											  .replace("[", "(")\
											  .replace("]", ")")\
											  .replace(") & (", ") | (")\
											  .replace("\'", "")

			new_pstring += ors + ")"

			pstring_dict[action] = expr(new_pstring).to_nnf()

	return pstring_dict

def make_condition_node(sym_lookup_dict, every_operand):
	need_inverter = False
	value = str(ast2expr(every_operand))
	if value[0] == "~":
		need_inverter = True
		value = value[1]

	condition = get_key(sym_lookup_dict, value)

	node = py_trees.behaviours.Success(name = condition)
	if need_inverter:
		node = py_trees.decorators.Inverter(node, name = "Inverter")

	return node

def recursive_build(pstring_expr, sym_lookup_dict):
	# print("pstring_expr: {}".format(pstring_expr))
	operator = pstring_expr.to_ast()[0]
	new_branch = None
	recursive = False
	if operator == AND:
		recursive = True
		new_branch = py_trees.composites.Sequence(name = "Sequence")
	elif operator == OR:
		recursive = True
		new_branch = py_trees.composites.Selector(name = "Selector")
	else:
		# print("making use of new part...")
		new_branch = make_condition_node(sym_lookup_dict, pstring_expr.to_ast())

	if recursive:
		for every_operand in pstring_expr.to_ast()[1:]:
			# print("every_operand: {}".format(every_operand))
			if every_operand[0] == AND or every_operand[0] == OR:
				node = recursive_build(ast2expr(every_operand), sym_lookup_dict)
				new_branch.add_child(node)
			else:
				condition_node = make_condition_node(sym_lookup_dict, every_operand)
				new_branch.add_child(condition_node)

	return new_branch

def pstring_to_btree(action_dict, sym_lookup_dict):
	root = py_trees.composites.Parallel(name = "Parallel Root")
	# print(action_dict)
	for action in action_dict:
		behavior_node = recursive_build(action_dict[action], sym_lookup_dict)
		action_node = py_trees.behaviours.Success(name = action)
		if isinstance(behavior_node, py_trees.decorators.Inverter):
			temp_sequence = py_trees.composites.Sequence(name = "Sequence")
			temp_sequence.add_child(behavior_node)
			behavior_node = temp_sequence
		behavior_node.add_child(action_node)
		root.add_child(behavior_node)
	# save_tree(root)
	return root

def max_prune(dt):
	return is_leaf_node(dt, 0)

def bt_espresso_mod(dt, feature_names, label_names):
	if max_prune(dt): 
		return py_trees.composites.Parallel(name = "Parallel Root")
	sym_lookup, action_to_pstring = dt_to_pstring(dt, feature_names, label_names)
	action_minimized = {}
	for action in action_to_pstring:
		action_minimized[action] = espresso_exprs(expr(action_to_pstring[action]).to_dnf())[0] # logic minimization
	action_minimized = factorize_pstring(action_minimized) # factorize pstrings
	btree = pstring_to_btree(action_minimized, sym_lookup) # convert pstrings to btree
	return btree

def save_tree(tree, filename):
	py_trees.display.render_dot_tree(tree, name = constants.BEHAVIOR_TREE_XML_FILENAME, target_directory = filename)
