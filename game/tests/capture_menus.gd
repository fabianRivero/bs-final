extends SceneTree
## Capture a screenshot of the title and the ending screens.
##
## Run it with:
## [codeblock]
## Godot_v4.7.2-stable_win64_console.exe --path game --script res://tests/capture_menus.gd
## [/codeblock]

## Directory the screenshots are written to.
const OUTPUT_DIR: String = "user://screenshots"

## The number of frames to wait before the capture.
const SETTLE_FRAMES: int = 6

## The scene that is captured.
var _scene: Node = null

## The number of frames waited so far.
var _settle_counter: int = 0

## The index of the scene to capture.
var _capture_index: int = 0

## The scenes to capture, in order.
const SCENES: Array[String] = ["res://scenes/title.tscn", "res://scenes/ending.tscn"]


func _init() -> void:
	## Prepare the output directory and capture the first scene.
	print("=== Aldermere menu capture ===")
	DirAccess.make_dir_recursive_absolute(OUTPUT_DIR)
	_load_next()


## Load the next scene of the list.
func _load_next() -> void:
	if _capture_index >= SCENES.size():
		print("=== %d screenshots written to %s ===" % [
			SCENES.size(),
			ProjectSettings.globalize_path(OUTPUT_DIR),
		])
		quit(0)
		return
	var packed: PackedScene = load(SCENES[_capture_index])
	if packed == null:
		print("FAIL  could not load %s" % SCENES[_capture_index])
		_capture_index += 1
		_load_next()
		return
	_scene = packed.instantiate()
	root.add_child(_scene)
	_settle_counter = SETTLE_FRAMES


## Capture the frame buffer once the scene has settled.
func _process(_delta: float) -> bool:
	if _settle_counter > 0:
		_settle_counter -= 1
		if _settle_counter > 0:
			return false
		var path: String = "%s/menu_%s.png" % [OUTPUT_DIR, SCENES[_capture_index].get_file().get_basename()]
		var image: Image = root.get_texture().get_image()
		var error: int = image.save_png(path)
		if error != OK:
			print("FAIL  could not write %s (error %d)" % [path, error])
		else:
			print("PASS  %s -> %s" % [SCENES[_capture_index], path])
		if _scene != null:
			_scene.queue_free()
			_scene = null
		_capture_index += 1
		_load_next()
	return false
