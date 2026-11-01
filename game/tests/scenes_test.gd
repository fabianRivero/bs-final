extends SceneTree
## Boot test: load each scene of the game and check that it builds.
##
## The three scenes of the game are the title, the playable zone and the
## ending. The test loads each one in turn, the way the scene router does,
## and checks that the hierarchy the scene is supposed to build is there.
##
## Run it with:
## [codeblock]
## Godot_v4.7.2-stable_win64_console.exe --headless --path game --script res://tests/scenes_test.gd
## [/codeblock]

## Number of assertions that passed.
var _passed: int = 0

## Number of assertions that failed.
var _failed: int = 0

## Whether the test has already run.
var _has_run: bool = false


func _init() -> void:
	## Boot the title scene and report the outcome.
	print("=== Aldermere scenes test ===")


## Run the assertions once the scene tree has processed a frame.
func _process(_delta: float) -> bool:
	if _has_run:
		return true
	_has_run = true

	_test_title()
	_test_game()
	_test_ending()

	print("")
	print("=== Result: %d passed, %d failed ===" % [_passed, _failed])
	if _failed > 0:
		quit(1)
	else:
		quit(0)
	return true


#region Assertions

## Record the outcome of one assertion.
##
## @param label Description of the assertion.
## @param condition Whether the assertion holds.
## @param detail Extra information printed when the assertion fails.
func _check(label: String, condition: bool, detail: String = "") -> void:
	if condition:
		_passed += 1
		print("PASS  %s" % label)
	else:
		_failed += 1
		if detail.is_empty():
			print("FAIL  %s" % label)
		else:
			print("FAIL  %s -> %s" % [label, detail])


## Assert that two values are equal.
##
## @param label Description of the assertion.
## @param actual The value produced by the game.
## @param expected The value produced by the Python core.
func _check_equal(label: String, actual: Variant, expected: Variant) -> void:
	_check(
		label,
		actual == expected,
		"expected %s, got %s" % [str(expected), str(actual)]
	)

#endregion


#region Scenes

## Load a scene and add it to the tree.
##
## @param path Path of the scene to load.
## @return The instantiated scene, or `null` when it could not be loaded.
func _load_scene(path: String) -> Node:
	var packed: PackedScene = load(path)
	if packed == null:
		return null
	var scene: Node = packed.instantiate()
	root.add_child(scene)
	return scene


## Check that the title scene builds.
func _test_title() -> void:
	print("")
	print("-- title --")
	var scene: Node = _load_scene("res://scenes/title.tscn")
	_check("the title scene loads", scene != null)
	if scene == null:
		return

	var title_label: Node = scene.get_node_or_null("Column/TitleLabel")
	_check("the title scene shows the title of the game", title_label != null)
	if title_label != null:
		_check_equal("the title is ALDERMERE", title_label.get("text"), "ALDERMERE")

	var status_label: Node = scene.get_node_or_null("Column/StatusLabel")
	_check("the title scene reports the state of the content", status_label != null)
	if status_label != null:
		_check(
			"the title scene found the content",
			String(status_label.get("text")).contains("content loaded"),
			String(status_label.get("text"))
		)

	scene.queue_free()


## Check that the playable scene builds.
func _test_game() -> void:
	print("")
	print("-- game --")
	var scene: Node = _load_scene("res://scenes/game.tscn")
	_check("the game scene loads", scene != null)
	if scene == null:
		return

	_check("the game scene holds a world view", scene.get("world_view") != null)
	_check("the game scene holds a player", scene.get("player") != null)
	_check("the game scene holds a hud", scene.get("hud") != null)
	_check("the game scene holds a dialogue panel", scene.get("dialogue_ui") != null)

	var hud: Node = scene.get("hud")
	if hud != null:
		var clock_label: Node = hud.get("clock_label")
		_check("the hud holds a clock label", clock_label != null)
		if clock_label != null:
			_check_equal(
				"the hud starts at the beginning of the cycle",
				clock_label.get("text"),
				"Day 1 00:00"
			)
		var cycle_bar: Node = hud.get("cycle_bar")
		_check("the hud holds the cycle bar", cycle_bar != null)
		if cycle_bar != null:
			_check_equal(
				"the cycle bar spans the whole cycle",
				int(cycle_bar.get("max_value")),
				288
			)

	scene.queue_free()


## Check that the ending scene builds.
func _test_ending() -> void:
	print("")
	print("-- ending --")
	var scene: Node = _load_scene("res://scenes/ending.tscn")
	_check("the ending scene loads", scene != null)
	if scene == null:
		return

	var title_label: Node = scene.get_node_or_null("Column/TitleLabel")
	_check("the ending scene shows a title", title_label != null)
	if title_label != null:
		_check_equal(
			"the ending scene is the placeholder of F5",
			title_label.get("text"),
			"ENDING SCREEN"
		)

	var text_label: Node = scene.get_node_or_null("Column/TextLabel")
	_check("the ending scene shows the placeholder text", text_label != null)
	if text_label != null:
		_check(
			"the ending scene says it is implemented in F5",
			String(text_label.get("text")).contains("F5"),
			String(text_label.get("text"))
		)

	scene.queue_free()

#endregion
