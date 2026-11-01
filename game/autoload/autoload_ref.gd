extends RefCounted
class_name AutoloadRef
## Runtime lookup of the autoloads of the project.
##
## Godot exposes the autoloads as **global identifiers** (``GameState``,
## ``ContentDb``, ...). Those identifiers are resolved at compile time from the
## project settings, which means a script cannot refer to them when it runs
## outside the main scene loop — a script launched with ``--script``, for
## instance, runs before the scene tree starts processing, so neither the
## autoload singletons nor ``get_tree()`` are available.
##
## This class solves that with a small **registry**: every autoload registers
## itself when it enters the tree, and the lookups go through the registry
## first. The scene tree is only used as a fallback, for the case where an
## autoload was created without registering itself.
##
## The registry is what lets the smoke test drive the very same scripts the
## game runs, without a special build of the project.
##
## The rule is simple: the game code uses these helpers instead of the global
## identifiers, and the lookups are cheap.

## Registry of the autoloads, keyed by their node name.
static var _registry: Dictionary = {}


## Register an autoload.
##
## The autoloads call this in their ``_ready()``. Registering twice is
## harmless: the last registration wins.
##
## @param node_name Name of the autoload, e.g. `"GameState"`.
## @param node The autoload node.
static func register(node_name: String, node: Node) -> void:
	if node == null or not is_instance_valid(node):
		return
	_registry[node_name] = node


## Unregister an autoload.
##
## @param node_name Name of the autoload, e.g. `"GameState"`.
static func unregister(node_name: String) -> void:
	_registry.erase(node_name)


## Return an autoload by name.
##
## @param node_name Name of the autoload, e.g. `"GameState"`.
## @param anchor Node used to find the scene tree when the autoload is not
##        registered. Usually the calling node.
## @return The autoload node, or `null` when it is not available.
static func get_node_or_null(node_name: String, anchor: Node = null) -> Node:
	if _registry.has(node_name):
		var registered: Variant = _registry[node_name]
		if registered is Node and is_instance_valid(registered):
			return registered as Node
		_registry.erase(node_name)

	var tree: SceneTree = _resolve_tree(anchor)
	if tree == null or tree.root == null:
		return null
	var found: Node = tree.root.get_node_or_null(NodePath(node_name))
	if found != null:
		_registry[node_name] = found
	return found


## Resolve the scene tree the autoloads live in.
##
## @param anchor Node whose tree is searched first.
## @return The scene tree, or `null` when it cannot be resolved.
static func _resolve_tree(anchor: Node = null) -> SceneTree:
	if anchor != null and is_instance_valid(anchor):
		var anchor_tree: SceneTree = anchor.get_tree()
		if anchor_tree != null:
			return anchor_tree
	var loop: MainLoop = Engine.get_main_loop()
	if loop is SceneTree:
		return loop as SceneTree
	return null


## Return the game state autoload.
##
## @param anchor Node whose tree is searched first.
## @return The game state node, or `null` when it is not available.
static func game_state(anchor: Node = null) -> Node:
	return get_node_or_null("GameState", anchor)


## Return the content database autoload.
##
## @param anchor Node whose tree is searched first.
## @return The content database node, or `null` when it is not available.
static func content_db(anchor: Node = null) -> Node:
	return get_node_or_null("ContentDb", anchor)


## Return the lighting autoload.
##
## @param anchor Node whose tree is searched first.
## @return The lighting node, or `null` when it is not available.
static func lighting(anchor: Node = null) -> Node:
	return get_node_or_null("Lighting", anchor)


## Return the scene router autoload.
##
## @param anchor Node whose tree is searched first.
## @return The scene router node, or `null` when it is not available.
static func scene_router(anchor: Node = null) -> Node:
	return get_node_or_null("SceneRouter", anchor)


## Forget the registered autoloads.
static func clear_registry() -> void:
	_registry.clear()
