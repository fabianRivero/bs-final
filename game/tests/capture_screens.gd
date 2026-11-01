extends SceneTree
## Capture a screenshot of the playable scene at every lighting phase.
##
## The script boots the playable scene, walks the clock through the seven
## phases of the daily cycle and writes one PNG per phase. The images are the
## demo material that shows the day/night cycle of Aldermere.
##
## The script is **not** a test: it produces artefacts. It is kept with the
## tests because it is the tool that proves the lighting is visible.
##
## Run it with:
## [codeblock]
## Godot_v4.7.2-stable_win64_console.exe --path game --script res://tests/capture_screens.gd
## [/codeblock]
##
## The rendering needs a real display driver, so the script must **not** be
## run with ``--headless``.

## Directory the screenshots are written to.
const OUTPUT_DIR: String = "user://screenshots"

## The ticks that are captured, one per lighting phase.
const CAPTURED_TICKS: Array[int] = [0, 20, 30, 50, 70, 79, 90]

## The number of frames to wait after a phase change, so the overlay settles.
const SETTLE_FRAMES: int = 6

## The scene that is captured.
var _scene: Node = null

## The number of frames waited since the last phase change.
var _settle_counter: int = 0

## The index of the next tick to capture.
var _capture_index: int = 0

## Whether the capture is over.
var _has_finished: bool = false


func _init() -> void:
	## Boot the playable scene and prepare the output directory.
	print("=== Aldermere screenshot capture ===")
	DirAccess.make_dir_recursive_absolute(OUTPUT_DIR)

	var packed: PackedScene = load("res://scenes/game.tscn")
	if packed == null:
		print("FAIL  the game scene could not be loaded")
		quit(1)
		return
	_scene = packed.instantiate()
	root.add_child(_scene)


## Capture the phases one by one.
##
## The capture is a small state machine: the clock is moved, the scene is
## given a few frames to settle, and the frame buffer is then written out.
func _process(_delta: float) -> bool:
	if _has_finished:
		return true

	var game_state: Node = AutoloadRef.game_state()
	var lighting: Node = AutoloadRef.lighting()
	if game_state == null or lighting == null:
		print("FAIL  the autoloads of the project were not created")
		quit(1)
		return true

	if _settle_counter > 0:
		_settle_counter -= 1
		if _settle_counter > 0:
			return false
		# The scene has settled: this is the frame that is written out.
		_write_capture()
		return false

	if _capture_index >= CAPTURED_TICKS.size():
		_has_finished = true
		print("=== %d screenshots written to %s ===" % [
			CAPTURED_TICKS.size(),
			ProjectSettings.globalize_path(OUTPUT_DIR),
		])
		quit(0)
		return true

	var tick_index: int = CAPTURED_TICKS[_capture_index]
	game_state.tick = tick_index
	game_state.emit_signal("tick_changed", tick_index, game_state.state())
	_settle_counter = SETTLE_FRAMES
	return false


## Write the frame buffer to the screenshot of the current phase.
func _write_capture() -> void:
	var lighting: Node = AutoloadRef.lighting()
	if lighting == null:
		return
	var tick_index: int = CAPTURED_TICKS[_capture_index]
	var path: String = "%s/phase_%s_tick_%03d.png" % [
		OUTPUT_DIR,
		lighting.current_phase_id,
		tick_index,
	]
	var image: Image = root.get_texture().get_image()
	var error: int = image.save_png(path)
	if error != OK:
		print("FAIL  could not write %s (error %d)" % [path, error])
	else:
		print("PASS  tick %3d -> %-12s -> %s" % [
			tick_index,
			lighting.current_phase_id,
			path,
		])
	_capture_index += 1
