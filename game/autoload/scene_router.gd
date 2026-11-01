extends Node
## Autoload that owns the scene transitions of the game.
##
## The game has three scenes: the title, the playable zone and the ending.
## The router is the only place that knows how to move between them, so no
## other system has to hold a scene path.

## Emitted when the router changes scene.
signal scene_changed(scene_name: String)

## Path of the title scene.
const TITLE_SCENE: String = "res://scenes/title.tscn"

## Path of the playable game scene.
const GAME_SCENE: String = "res://scenes/game.tscn"

## Path of the ending scene.
const ENDING_SCENE: String = "res://scenes/ending.tscn"

## The name of the scene currently displayed.
var current_scene_name: String = ""


func _ready() -> void:
	## Register the router so the other systems can reach it at runtime.
	AutoloadRef.register("SceneRouter", self)


## Change to another scene.
##
## @param scene_path Path of the scene to load.
## @return `true` when the change was requested successfully.
func goto_scene(scene_path: String) -> bool:
	if not ResourceLoader.exists(scene_path):
		push_error("SceneRouter: cannot find scene %s" % scene_path)
		return false

	var error: int = get_tree().change_scene_to_file(scene_path)
	if error != OK:
		push_error("SceneRouter: failed to change scene to %s (error %d)" % [scene_path, error])
		return false
	current_scene_name = scene_path.get_file().get_basename()
	scene_changed.emit(current_scene_name)
	return true


## Change to the title screen.
##
## @return `true` when the change was requested successfully.
func goto_title() -> bool:
	return goto_scene(TITLE_SCENE)


## Change to the playable scene.
##
## @return `true` when the change was requested successfully.
func goto_game() -> bool:
	return goto_scene(GAME_SCENE)


## Change to the ending screen.
##
## @return `true` when the change was requested successfully.
func goto_ending() -> bool:
	return goto_scene(ENDING_SCENE)
