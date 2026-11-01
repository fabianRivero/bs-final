extends Node
## Autoload that loads and caches the exported game content.
##
## The content is a single JSON document produced by `tools/export_web.py` from
## the Python simulation core. Godot never writes it and never interprets its
## meaning: it reads zones, NPCs and the lighting table so it can *present*
## them.
##
## The document is loaded once and cached. A missing or malformed document is
## reported loudly rather than silently ignored, because an empty world is
## indistinguishable from a bug.
##
## The load is **lazy**: the lookup tables are filled on the first access, so
## the order in which the engine creates the autoloads and the scenes does not
## matter. A scene may ask for a zone before the content autoload has had its
## turn, and it still gets the right answer.

## Path of the exported content document.
const CONTENT_PATH: String = "res://data/game_content.json"

## Emitted once the content document has been loaded successfully.
signal content_loaded

## The parsed content document, or an empty dictionary when the load failed.
var content: Dictionary = {}

## Whether the content document was loaded successfully.
var is_loaded: bool = false

## Zones of the world, keyed by zone id.
var _zones: Dictionary = {}

## NPCs of the world, keyed by NPC id.
var _npcs: Dictionary = {}

## Lighting phases of the daily cycle, ordered by `start_tick`.
var _lighting_phases: Array = []

## Provisions of the town, in the order the content document declares them.
var _resources: Array = []


func _ready() -> void:
	## Register the autoload and load the content as soon as it enters the
	## tree, so every other system can rely on it being available.
	AutoloadRef.register("ContentDb", self)
	load_content()


#region Accessors

## Return the zones of the world, keyed by zone id.
##
## @return The zone documents.
var zones: Dictionary:
	get:
		_ensure_loaded()
		return _zones

## Return the NPCs of the world, keyed by NPC id.
##
## @return The NPC documents.
var npcs: Dictionary:
	get:
		_ensure_loaded()
		return _npcs

## Return the lighting phases of the daily cycle, ordered by `start_tick`.
##
## @return The lighting phase documents.
var lighting_phases: Array:
	get:
		_ensure_loaded()
		return _lighting_phases

## Return the provisions of the town.
##
## @return The resource documents, in the order the content declares them.
var resources: Array:
	get:
		_ensure_loaded()
		return _resources

#endregion


#region Loading

## Load and cache the exported content document.
##
## @return `true` when the document was loaded and parsed successfully.
func load_content() -> bool:
	_zones = {}
	_npcs = {}
	_lighting_phases = []
	_resources = []
	is_loaded = false

	if not FileAccess.file_exists(CONTENT_PATH):
		push_error(
			"ContentDb: %s is missing. Run `uv run python -m tools.export_web` to export it."
			% CONTENT_PATH
		)
		content = {}
		return false

	var file: FileAccess = FileAccess.open(CONTENT_PATH, FileAccess.READ)
	if file == null:
		push_error(
			"ContentDb: cannot open %s (error %d)" % [CONTENT_PATH, FileAccess.get_open_error()]
		)
		content = {}
		return false

	var text: String = file.get_as_text()
	file.close()

	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("ContentDb: %s does not contain a JSON object." % CONTENT_PATH)
		content = {}
		return false

	content = parsed
	_index_content()
	is_loaded = true
	content_loaded.emit()
	return true


## Load the content when it has not been loaded yet.
func _ensure_loaded() -> void:
	if is_loaded:
		return
	if content.is_empty():
		load_content()


## Build the lookup tables over the parsed document.
func _index_content() -> void:
	_zones = {}
	for raw_zone in content.get("zones", []):
		if raw_zone is Dictionary and raw_zone.has("id"):
			_zones[String(raw_zone["id"])] = raw_zone

	_npcs = {}
	for raw_npc in content.get("npcs", []):
		if raw_npc is Dictionary and raw_npc.has("id"):
			_npcs[String(raw_npc["id"])] = raw_npc

	_lighting_phases = []
	for raw_phase in content.get("lighting", []):
		if raw_phase is Dictionary:
			_lighting_phases.append(raw_phase)
	_lighting_phases.sort_custom(
		func(a: Dictionary, b: Dictionary) -> bool:
			return int(a.get("start_tick", 0)) < int(b.get("start_tick", 0))
	)

	_resources = []
	for raw_resource in content.get("resources", []):
		if raw_resource is Dictionary:
			_resources.append(raw_resource)

#endregion


#region Queries

## Return the zone with the given id.
##
## @param zone_id Id of the zone.
## @return The zone document, or an empty dictionary when it does not exist.
func zone(zone_id: String) -> Dictionary:
	return zones.get(zone_id, {})


## Return the NPC with the given id.
##
## @param npc_id Id of the NPC.
## @return The NPC document, or an empty dictionary when it does not exist.
func npc(npc_id: String) -> Dictionary:
	return npcs.get(npc_id, {})


## Return every zone document.
##
## @return The zone documents.
func all_zones() -> Array:
	return zones.values()


## Return every NPC document.
##
## @return The NPC documents.
func all_npcs() -> Array:
	return npcs.values()


## Return the id of the first zone of the world.
##
## The F3 prototype only ships one playable zone; the id is read from the
## content document instead of being hard-coded.
##
## @return The zone id, or an empty string when the world has no zones.
func first_zone_id() -> String:
	var ids: Array = zones.keys()
	ids.sort()
	if ids.is_empty():
		return ""
	return String(ids[0])

#endregion
