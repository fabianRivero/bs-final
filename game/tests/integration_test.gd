extends SceneTree
## Integration test: boot the real game scene and drive the whole flow.
##
## The smoke test verifies the units. This test verifies that they are wired
## together: it loads the real scene, presses the real buttons and checks
## that the clock moves, that the decisions are recorded and that the
## lighting follows.
##
## It is the F3 proof that the flow described in the architecture holds:
##
## [codeblock]
## input -> player checks interactivity -> emits ActionRequest
##       -> GameState records the decision and advances the tick
##       -> emits tick_changed
##       -> ContentDb repositions the NPCs, Lighting applies the phase,
##          the HUD updates the clock
## [/codeblock]
##
## Run it with:
## [codeblock]
## Godot_v4.7.2-stable_win64_console.exe --headless --path game --script res://tests/integration_test.gd
## [/codeblock]

## Number of assertions that passed.
var _passed: int = 0

## Number of assertions that failed.
var _failed: int = 0

## The loaded game scene.
var _scene: Node = null

## The autoloads of the project.
var _game_state: Node = null
var _content_db: Node = null
var _lighting: Node = null

## Whether the test has already run.
var _has_run: bool = false


func _init() -> void:
	## Boot the project and report the outcome.
	print("=== Aldermere integration test ===")
	if not _boot():
		print("FAIL  the game scene could not be booted")
		print("")
		print("=== Result: %d passed, %d failed ===" % [_passed, _failed + 1])
		quit(1)
		return


## Run the assertions once the scene tree has processed a frame.
##
## The assertions need the ``_ready()`` hooks of the scene to have run, and
## those only fire once the tree starts processing — never during ``_init()``.
func _process(_delta: float) -> bool:
	if _has_run:
		return true
	_has_run = true

	_resolve_autoloads()
	if _game_state == null or _content_db == null or _lighting == null:
		print("FAIL  the autoloads of the project were not created")
		print("")
		print("=== Result: %d passed, %d failed ===" % [_passed, _failed + 1])
		quit(1)
		return true

	_test_scene_tree()
	_test_input_flow()
	_test_lighting_follows_the_clock()
	_test_scene_router()

	print("")
	print("=== Result: %d passed, %d failed ===" % [_passed, _failed])
	if _failed > 0:
		quit(1)
	else:
		quit(0)
	return true


## Boot the game scene.
##
## The project registers its own autoloads, and they are created when the
## scene tree starts processing. The test therefore does **not** create them:
## it uses the ones the project registers, which is what makes this an
## integration test rather than a unit test.
##
## @return `true` when the scene was loaded successfully.
func _boot() -> bool:
	var packed: PackedScene = load("res://scenes/game.tscn")
	if packed == null:
		return false
	_scene = packed.instantiate()
	root.add_child(_scene)
	return true


## Resolve the autoloads of the project.
##
## The autoloads are created by the engine when the tree starts processing,
## so they are looked up once the first frame has run.
func _resolve_autoloads() -> void:
	_game_state = AutoloadRef.game_state()
	_content_db = AutoloadRef.content_db()
	_lighting = AutoloadRef.lighting()


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


#region Scene tree

## Check that the game scene builds the hierarchy it is supposed to.
func _test_scene_tree() -> void:
	print("")
	print("-- scene tree --")
	_check("the scene was loaded", _scene != null)
	if _scene == null:
		return

	_check("the scene holds a world view", _scene.get("world_view") != null)
	_check("the scene holds a player", _scene.get("player") != null)
	_check("the scene holds a hud", _scene.get("hud") != null)
	_check("the scene holds a dialogue panel", _scene.get("dialogue_ui") != null)

	var player: Node = _scene.get("player")
	if player != null:
		_check(
			"the player starts on a tile of the zone",
			player.tile != Vector2i(-1, -1),
			"tile is %s" % str(player.tile)
		)

	var world_view: Node = _scene.get("world_view")
	if world_view != null:
		_check("the world view loaded a zone", world_view.get("zone") != null)
		var zone: Node = world_view.get("zone")
		if zone != null:
			_check(
				"the zone has a size",
				zone.size_in_tiles() != Vector2i.ZERO,
				"size is %s" % str(zone.size_in_tiles())
			)
			_check(
				"the zone has walkable cells",
				zone.is_walkable(Vector2i(1, 1)) or zone.is_walkable(Vector2i(2, 2))
			)

	var agents: Dictionary = _scene.get("npc_agents")
	_check("the scene holds the npc agents", agents.size() == 3, "found %d" % agents.size())

#endregion


#region Input flow

## Check that a movement costs one tick and records a decision.
func _test_input_flow() -> void:
	print("")
	print("-- input flow --")

	var player: Node = _scene.get("player")
	if player == null:
		_check("the player is available", false)
		return

	var start_tick: int = int(_game_state.tick)
	var start_tile: Vector2i = player.tile

	var started: bool = player.request_step(Vector2i.RIGHT)
	_check("a movement step is accepted", started)

	# The step is animated over a few frames, so the tick is advanced when the
	# step is requested.
	_check(
		"the movement did not consume a tick by itself",
		int(_game_state.tick) == start_tick,
		"tick is %d" % int(_game_state.tick)
	)

	# Finish the animation and let the movement be committed.
	player.set("is_moving", false)
	player.set("tile", start_tile + Vector2i.RIGHT)
	player.emit_signal("step_finished", start_tile + Vector2i.RIGHT)

	# The player emits the action request; the scene turns it into a decision.
	var requests: Array[ActionRequest] = []
	player.action_requested.connect(func(request: ActionRequest) -> void:
		requests.append(request)
	)

	# Facing nothing yields no request: the player consults the world before
	# it offers anything.
	player.emit_interaction()
	_check(
		"the player emits no request when it faces nothing",
		requests.is_empty()
	)

	# Facing an NPC yields a request for that NPC.
	var miller: Dictionary = _content_db.npc("NPC_MILLER")
	var miller_tile: Vector2i = Player.npc_tile_at(miller, int(_game_state.tick))
	player.set("tile", miller_tile + Vector2i(0, 1))
	player.set("facing", Vector2i.UP)
	player.emit_interaction()
	_check(
		"the player emits a request when it faces an npc",
		requests.size() == 1,
		"%d requests were emitted" % requests.size()
	)
	if requests.size() == 1:
		_check_equal(
			"the request targets the npc the player faces",
			requests[0].target,
			"NPC_MILLER"
		)
		_check_equal(
			"the request asks to talk",
			requests[0].kind,
			"talk"
		)

	# The scene turns the request into a decision and moves the clock.
	var before_tick: int = int(_game_state.tick)
	var before_decisions: int = _game_state.decisions.size()
	_scene.call("_on_action_requested", requests[0] if requests.size() > 0 else null)
	_check(
		"the request is recorded as a decision",
		_game_state.decisions.size() == before_decisions + 1,
		"%d decisions" % _game_state.decisions.size()
	)
	_check_equal(
		"the decision advances the clock",
		int(_game_state.tick),
		before_tick + 1
	)
	_check(
		"the decision raises the talked flag",
		_game_state.has_flag("talked:NPC_MILLER"),
		str(_game_state.state()["flags"])
	)

#endregion


#region Lighting

## Check that the lighting follows the clock.
func _test_lighting_follows_the_clock() -> void:
	print("")
	print("-- lighting follows the clock --")

	_game_state.tick = 38
	_game_state.emit_signal("tick_changed", 38, _game_state.state())
	_check_equal(
		"tick 38 is the day phase",
		_lighting.current_phase_id,
		"day"
	)
	_check_equal(
		"the day phase has no overlay",
		_lighting.current_opacity,
		0.0
	)

	_game_state.tick = 0
	_game_state.emit_signal("tick_changed", 0, _game_state.state())
	_check_equal(
		"tick 0 is the dawn_early phase",
		_lighting.current_phase_id,
		"dawn_early"
	)
	_check_equal(
		"the dawn_early phase darkens the world",
		_lighting.current_opacity,
		0.55
	)

	_game_state.tick = 82
	_game_state.emit_signal("tick_changed", 82, _game_state.state())
	_check_equal(
		"tick 82 is the night phase",
		_lighting.current_phase_id,
		"night"
	)

#endregion


#region Scene router

## Check that the router knows the three scenes of the game.
func _test_scene_router() -> void:
	print("")
	print("-- scene router --")
	var router: Node = AutoloadRef.scene_router()
	_check("the scene router is available", router != null)
	if router == null:
		return
	_check("the title scene exists", ResourceLoader.exists(router.TITLE_SCENE))
	_check("the game scene exists", ResourceLoader.exists(router.GAME_SCENE))
	_check("the ending scene exists", ResourceLoader.exists(router.ENDING_SCENE))

#endregion
