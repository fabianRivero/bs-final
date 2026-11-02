extends SceneTree
## Smoke test of the Godot presentation layer.
##
## The test runs headless and prints one PASS/FAIL line per assertion. It
## covers the four things that can silently drift between Python and Godot:
##
## 1. the clock — the `(day, hour, minute)` triple and its labels;
## 2. the derivation — the flags produced by the decisions;
## 3. the lighting table — the seven phases and their boundaries;
## 4. the content document — the exported JSON contract.
##
## The autoloads are instantiated by the test itself rather than reached
## through their global names: a script run with ``--script`` does not get the
## autoload singletons of the project, so the test loads the very same
## scripts the project registers and drives them directly. What is tested is
## therefore the code that actually ships.
##
## The expected values are the ones of the Python core: ``core/time.py``,
## ``core/state.py`` and ``core/lighting.py``. This script is the local
## counterpart of ``tools/parity_check.py``, which does the exhaustive
## comparison in F5.
##
## It also pins down the **irreversible death** of a villager: the tick of
## the death is the tick at which the villager is already gone, and the
## design decision D33 forbids any counter of the dead in the HUD.
##
## Run it with:
## [codeblock]
## Godot_v4.7.2-stable_win64_console.exe --headless --path game --script res://tests/smoke_test.gd
## [/codeblock]

## Number of assertions that passed.
var _passed: int = 0

## Number of assertions that failed.
var _failed: int = 0

## The game state autoload, instantiated by the test.
var _game_state: Node = null

## The content database autoload, instantiated by the test.
var _content_db: Node = null

## The lighting autoload, instantiated by the test.
var _lighting: Node = null


func _init() -> void:
	## Run every group of assertions and report the outcome.
	print("=== Aldermere smoke test ===")
	if not _instantiate_autoloads():
		print("FAIL  the autoloads could not be instantiated")
		print("")
		print("=== Result: %d passed, %d failed ===" % [_passed, _failed + 1])
		quit(1)
		return

	_test_clock()
	_test_derive()
	_test_lighting()
	_test_content()
	_test_resources()
	_test_resource_rules()
	_test_death()

	print("")
	print("=== Result: %d passed, %d failed ===" % [_passed, _failed])
	if _failed > 0:
		quit(1)
	else:
		quit(0)


## Instantiate the autoloads of the project under test.
##
## The autoloads are driven explicitly rather than through their `_ready()`
## hooks: a script run with ``--script`` executes its ``_init()`` before the
## scene tree starts processing, so the ``_ready`` notification never arrives.
## The test therefore registers the autoloads by hand — exactly what their
## ``_ready()`` does in the running game — and calls the public API of each.
## What is tested is the code that actually ships.
##
## @return `true` when all three autoloads could be instantiated.
func _instantiate_autoloads() -> bool:
	var state_script: Script = load("res://autoload/game_state.gd")
	var content_script: Script = load("res://autoload/content_db.gd")
	var lighting_script: Script = load("res://autoload/lighting.gd")
	if state_script == null or content_script == null or lighting_script == null:
		return false

	_game_state = state_script.new()
	_game_state.name = "GameState"
	root.add_child(_game_state)
	AutoloadRef.register("GameState", _game_state)

	_content_db = content_script.new()
	_content_db.name = "ContentDb"
	root.add_child(_content_db)
	AutoloadRef.register("ContentDb", _content_db)
	_content_db.load_content()

	_lighting = lighting_script.new()
	_lighting.name = "Lighting"
	root.add_child(_lighting)
	AutoloadRef.register("Lighting", _lighting)
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


#region Clock

## Check the calendar arithmetic against the values of ``core/time.py``.
func _test_clock() -> void:
	print("")
	print("-- clock --")
	_check_equal("tick 0 is Day 1 00:00", _game_state.format_clock(0), "Day 1 00:00")
	_check_equal("tick 28 is Day 1 07:00", _game_state.format_clock(28), "Day 1 07:00")
	_check_equal("tick 29 is Day 1 07:15", _game_state.format_clock(29), "Day 1 07:15")
	_check_equal("tick 95 is Day 1 23:45", _game_state.format_clock(95), "Day 1 23:45")
	_check_equal("tick 96 is Day 2 00:00", _game_state.format_clock(96), "Day 2 00:00")
	_check_equal("tick 480 closes at Day 6 00:00", _game_state.format_clock(480), "Day 6 00:00")

	var instant_28: Dictionary = _game_state.to_datetime(28)
	_check_equal("tick 28 hour", instant_28["hour"], 7)
	_check_equal("tick 28 minute", instant_28["minute"], 0)
	_check_equal("tick 28 day", instant_28["day"], 1)

	var instant_29: Dictionary = _game_state.to_datetime(29)
	_check_equal("tick 29 hour", instant_29["hour"], 7)
	_check_equal("tick 29 minute", instant_29["minute"], 15)

	var instant_96: Dictionary = _game_state.to_datetime(96)
	_check_equal("tick 96 day", instant_96["day"], 2)
	_check_equal("tick 96 hour", instant_96["hour"], 0)
	_check_equal("tick 96 minute", instant_96["minute"], 0)

	var instant_480: Dictionary = _game_state.to_datetime(480)
	_check_equal("tick 480 day", instant_480["day"], 6)
	_check_equal("tick 480 hour", instant_480["hour"], 0)
	_check_equal("tick 480 minute", instant_480["minute"], 0)

	# Four consecutive ticks share the same (day, hour) pair: the minute is
	# what makes the triple lossless.
	var hours: Array[int] = []
	for tick_index in range(28, 32):
		hours.append(int(_game_state.to_datetime(tick_index)["hour"]))
	_check("ticks 28-31 share the same hour", hours[0] == hours[3] and hours[0] == 7)

#endregion


#region Derivation

## Check the local derivation against the flags of ``core/state.py``.
func _test_derive() -> void:
	print("")
	print("-- derive --")

	var empty_state: Dictionary = _game_state.derive(0, [])
	_check_equal("no decisions raise no flags", empty_state["flags"].size(), 0)

	var talk: Dictionary = {
		"kind": "talk", "target": "NPC_MILLER", "tick": 0, "payload": {},
	}
	var talk_state: Dictionary = _game_state.derive(0, [talk])
	_check(
		"a talk decision raises decided:talk and talked:NPC_MILLER",
		talk_state["flags"].has("decided:talk")
		and talk_state["flags"].has("talked:NPC_MILLER"),
		str(talk_state["flags"])
	)
	_check(
		"a talk decision raises exactly two flags",
		talk_state["flags"].size() == 2,
		str(talk_state["flags"])
	)

	var examine: Dictionary = {
		"kind": "examine", "target": "SYM_NUMBNESS", "tick": 0, "payload": {},
	}
	var examine_state: Dictionary = _game_state.derive(0, [examine])
	_check(
		"an examine decision raises examined:<target>",
		examine_state["flags"].has("examined:SYM_NUMBNESS")
		and examine_state["flags"].has("decided:examine"),
		str(examine_state["flags"])
	)

	var move: Dictionary = {
		"kind": "move", "target": "ZN_YARD", "tick": 0, "payload": {},
	}
	var move_state: Dictionary = _game_state.derive(0, [move])
	_check(
		"a move decision raises visited:<zone>",
		move_state["flags"].has("visited:ZN_YARD"),
		str(move_state["flags"])
	)

	var report: Dictionary = {
		"kind": "report_symptom", "target": "", "tick": 0,
		"payload": {"symptom": "SYM_RASH"},
	}
	var report_state: Dictionary = _game_state.derive(0, [report])
	_check(
		"a report_symptom decision raises knows:symptom:<id>",
		report_state["flags"].has("knows:symptom:SYM_RASH"),
		str(report_state["flags"])
	)

	var explicit: Dictionary = {
		"kind": "examine", "target": "SYM_NUMBNESS", "tick": 0,
		"payload": {"sets_flags": ["heard_about_mill", "asked_about_store"]},
	}
	var explicit_state: Dictionary = _game_state.derive(0, [explicit])
	_check(
		"the sets_flags payload raises explicit flags",
		explicit_state["flags"].has("heard_about_mill")
		and explicit_state["flags"].has("asked_about_store"),
		str(explicit_state["flags"])
	)

	# The flags depend only on the decisions, never on the tick.
	var decisions: Array = [talk, examine, move, report]
	var at_zero: Dictionary = _game_state.derive(0, decisions)
	var at_end: Dictionary = _game_state.derive(480, decisions)
	_check_equal(
		"the flags do not depend on the tick",
		at_zero["flags"],
		at_end["flags"]
	)

	# A decision without a target raises no target-specific flag.
	var empty_target: Dictionary = {
		"kind": "talk", "target": "", "tick": 0, "payload": {},
	}
	var empty_target_state: Dictionary = _game_state.derive(0, [empty_target])
	_check_equal(
		"a talk decision without a target raises one flag",
		empty_target_state["flags"].size(),
		1
	)

	# The flag vocabulary of the local derivation.
	var vocabulary: PackedStringArray = PackedStringArray([
		"decided:", "talked:", "examined:", "visited:", "knows:symptom:",
	])
	for decision in decisions:
		for flag_name in _game_state.flags_for_decision(decision):
			var matches: bool = false
			for prefix in vocabulary:
				if flag_name.begins_with(prefix):
					matches = true
					break
			_check(
				"the flag %s uses the canonical vocabulary" % flag_name,
				matches
			)

	# The clock is bounded: advancing past the closing tick is refused.
	_game_state.tick = 480
	var refused: bool = false
	_game_state.advance("talk", "NPC_MILLER")
	if _game_state.tick == 480:
		refused = true
	_check("the clock refuses to advance past the closing tick", refused)
	_game_state.tick = 0

#endregion


#region Lighting

## Check the lighting table against the values of ``core/lighting.py``.
func _test_lighting() -> void:
	print("")
	print("-- lighting --")

	var expected: Array = [
		["dawn_early", 0, 18, [40, 50, 90], 0.55],
		["dawn", 18, 26, [255, 170, 110], 0.25],
		["morning", 26, 38, [255, 214, 170], 0.08],
		["day", 38, 66, [255, 255, 255], 0.00],
		["afternoon", 66, 76, [255, 226, 180], 0.06],
		["dusk", 76, 82, [255, 150, 110], 0.28],
		["night", 82, 96, [40, 50, 90], 0.55],
	]

	_check_equal("the table holds seven phases", _content_db.lighting_phases.size(), 7)

	for entry in expected:
		var phase_id: String = String(entry[0])
		var start_tick: int = int(entry[1])
		var end_tick: int = int(entry[2])
		var expected_rgb: Array = entry[3]
		var expected_opacity: float = float(entry[4])

		var phase: Dictionary = _lighting.phase_at(start_tick)
		_check_equal("the phase at tick %d is %s" % [start_tick, phase_id],
			_lighting.phase_name(phase), phase_id)
		_check_equal(
			"the phase %s keeps its opacity" % phase_id,
			float(phase.get("opacity", -1.0)), expected_opacity
		)
		var rgb: Array = phase.get("rgb", [0, 0, 0])
		_check(
			"the phase %s keeps its rgb" % phase_id,
			rgb.size() == expected_rgb.size()
			and int(rgb[0]) == int(expected_rgb[0])
			and int(rgb[1]) == int(expected_rgb[1])
			and int(rgb[2]) == int(expected_rgb[2]),
			"expected %s, got %s" % [str(expected_rgb), str(rgb)]
		)

	# The last tick of a phase belongs to it; the first tick of the next one
	# does not.
	_check_equal("tick 17 is dawn_early", _lighting.phase_name(_lighting.phase_at(17)), "dawn_early")
	_check_equal("tick 18 is dawn", _lighting.phase_name(_lighting.phase_at(18)), "dawn")
	_check_equal("tick 25 is dawn", _lighting.phase_name(_lighting.phase_at(25)), "dawn")
	_check_equal("tick 26 is morning", _lighting.phase_name(_lighting.phase_at(26)), "morning")
	_check_equal("tick 37 is morning", _lighting.phase_name(_lighting.phase_at(37)), "morning")
	_check_equal("tick 38 is day", _lighting.phase_name(_lighting.phase_at(38)), "day")
	_check_equal("tick 65 is day", _lighting.phase_name(_lighting.phase_at(65)), "day")
	_check_equal("tick 66 is afternoon", _lighting.phase_name(_lighting.phase_at(66)), "afternoon")
	_check_equal("tick 75 is afternoon", _lighting.phase_name(_lighting.phase_at(75)), "afternoon")
	_check_equal("tick 76 is dusk", _lighting.phase_name(_lighting.phase_at(76)), "dusk")
	_check_equal("tick 81 is dusk", _lighting.phase_name(_lighting.phase_at(81)), "dusk")
	_check_equal("tick 82 is night", _lighting.phase_name(_lighting.phase_at(82)), "night")
	_check_equal("tick 95 is night", _lighting.phase_name(_lighting.phase_at(95)), "night")

	# The pattern repeats every day.
	_check_equal(
		"tick 124 repeats the phase of tick 28",
		_lighting.phase_name(_lighting.phase_at(124)),
		_lighting.phase_name(_lighting.phase_at(28))
	)

	# Every tick of the day belongs to exactly one phase.
	var covered: bool = true
	for tick_index in range(96):
		if _lighting.phase_at(tick_index).is_empty():
			covered = false
			break
	_check("every tick of the day belongs to a phase", covered)

	# The phase really is applied: the overlay tracks the phase.
	_lighting.apply_phase(38)
	_check_equal("the day phase has no overlay", _lighting.current_opacity, 0.0)
	_lighting.apply_phase(0)
	_check_equal("the dawn_early phase darkens the world", _lighting.current_opacity, 0.55)
	_check(
		"the dawn_early phase tints the world",
		_lighting.current_tint.is_equal_approx(
			Color(40.0 / 255.0, 50.0 / 255.0, 90.0 / 255.0)
		),
		"got %s" % str(_lighting.current_tint)
	)

#endregion


#region Content

## Check that the exported content document was loaded and is complete.
func _test_content() -> void:
	print("")
	print("-- content --")

	_check("the content document was loaded", _content_db.is_loaded)
	_check_equal("the document holds two zones", _content_db.zones.size(), 2)
	_check_equal("the document holds three npcs", _content_db.npcs.size(), 3)
	_check_equal("the document holds seven lighting phases", _content_db.lighting_phases.size(), 7)
	_check("the document holds the premise", _content_db.content.has("premise"))
	_check("the document holds the clock constants", _content_db.content.has("clock"))

	if _content_db.content.has("clock"):
		var clock: Dictionary = _content_db.content["clock"]
		_check_equal("the clock holds the minutes per tick", clock["minutes_per_tick"], 15)
		_check_equal("the clock holds the ticks per day", clock["ticks_per_day"], 96)
		_check_equal("the clock holds the cycle days", clock["cycle_days"], 5)
		_check_equal("the clock holds the total ticks", clock["total_ticks"], 480)

	_check("the document holds the resources", _content_db.content.has("resources"))
	_check_equal("the document holds three resources", _content_db.resources.size(), 3)

	var zone_id: String = _content_db.first_zone_id()
	_check("a zone can be selected", not zone_id.is_empty())
	var zone: Dictionary = _content_db.zone(zone_id)
	_check("the zone holds its size", zone.has("width") and zone.has("height"))

	var npc_id: String = "NPC_MILLER"
	var npc: Dictionary = _content_db.npc(npc_id)
	_check("the npc can be read", npc.has("schedule"))
	_check("the npc holds a schedule", npc.get("schedule", []).size() > 0)

	# The schedule of the NPC is a pure function of the tick.
	var npc_tile: Vector2i = Player.npc_tile_at(npc, 40)
	var npc_tile_later: Vector2i = Player.npc_tile_at(npc, 136)
	_check_equal(
		"the schedule of the npc repeats every day",
		npc_tile,
		npc_tile_later
	)

	# The NPC resolves to a different tile when the schedule says so.
	var npc_tile_evening: Vector2i = Player.npc_tile_at(npc, 80)
	_check(
		"the npc moves when its schedule changes",
		npc_tile != npc_tile_evening,
		"both tiles are %s" % str(npc_tile)
	)

#endregion


#region Resources

## Check the GDScript mirror of the provisions of the town.
##
## The amounts are the ones the exported content document declares, and the
## consumption mirrors `core.resources.consume`: the amounts are clamped to
## zero instead of going negative. The mirror also reproduces the two extra
## rules of the system: a critical resource doubles the price of the action
## it gates, and a depleted one refuses it outright.
func _test_resources() -> void:
	print("")
	print("-- resources --")

	_check_equal("the autoload holds three resources", _game_state.resources.size(), 3)

	var food_amount: int = _game_state.resource_amount("RES_FOOD")
	_check_equal("the food starts at its initial amount", food_amount, 24)
	_check_equal(
		"the medicine starts at its initial amount",
		_game_state.resource_amount("RES_MEDICINE"),
		10
	)
	_check_equal(
		"the fuel starts at its initial amount",
		_game_state.resource_amount("RES_FUEL"),
		8
	)
	_check("the town can afford an action at the start", _game_state.can_afford_action())
	_check("no resource is in crisis at the start", _game_state.resource_crisis().is_empty())

	# The exported document carries the two new fields.
	var fuel_spec: Dictionary = _game_state.resources.get("RES_FUEL", {})
	_check_equal("the fuel declares its daily decay", fuel_spec.get("daily_decay", -1), 1)
	_check_equal(
		"the fuel gates the preparation of the sample",
		fuel_spec.get("blocks_actions", []),
		["prepare_sample"]
	)

	# Consuming an action draws on the stores.
	_game_state.consume_action_resources("talk")
	_check_equal(
		"an action costs one unit of food",
		_game_state.resource_amount("RES_FOOD"),
		23
	)
	_check_equal(
		"an action costs one unit of medicine",
		_game_state.resource_amount("RES_MEDICINE"),
		9
	)
	_check_equal(
		"the amount spent today is recorded",
		_game_state.resource_spent_today("RES_FOOD"),
		1
	)

	# The amounts are clamped to zero: a resource never goes negative.
	for _i in range(30):
		_game_state.consume_action_resources("talk")
	_check(
		"the food never goes negative",
		_game_state.resource_amount("RES_FOOD") >= 0
	)
	_check(
		"the medicine never goes negative",
		_game_state.resource_amount("RES_MEDICINE") >= 0
	)
	_check(
		"the medicine ran out",
		_game_state.resource_amount("RES_MEDICINE") == 0
	)
	_check(
		"a depleted resource is in crisis",
		_game_state.is_resource_critical("RES_MEDICINE")
	)
	_check(
		"the crisis lists the exhausted resource",
		_game_state.resource_crisis().has("RES_MEDICINE")
	)
	_check(
		"the town can no longer afford an action",
		not _game_state.can_afford_action()
	)

	# A resource the town never stocked is absent, not empty.
	_check_equal("an untracked resource holds nothing", _game_state.resource_amount("RES_NONE"), 0)
	_check(
		"an untracked resource is not in crisis",
		not _game_state.is_resource_critical("RES_NONE")
	)

	_game_state.reset()
	_check_equal(
		"the reset restores the initial amount",
		_game_state.resource_amount("RES_FOOD"),
		24
	)
	_check_equal(
		"the reset clears the daily spending",
		_game_state.resource_spent_today("RES_FOOD"),
		0
	)

#endregion


#region The critical multiplier and the blocked actions

## Check that the GDScript mirror reproduces the two extra rules of the
## provisions: a critical resource doubles the price of the action it gates,
## and a depleted one refuses it outright.
func _test_resource_rules() -> void:
	print("")
	print("-- resource rules --")

	# The fuel starts at 8 with a threshold of 2. The threshold is
	# exclusive, so the fuel is healthy at 2 and becomes critical at 1:
	# seven plain preparations bring it down to 1.
	_check_equal("the fuel starts healthy", _game_state.resource_state("RES_FUEL"), "healthy")
	for _i in range(7):
		_game_state.consume_action_resources("prepare_sample")
	_check_equal(
		"the fuel is below its threshold after seven preparations",
		_game_state.resource_amount("RES_FUEL"),
		1
	)
	_check_equal(
		"the fuel is in crisis after seven preparations",
		_game_state.resource_state("RES_FUEL"),
		"critical"
	)

	# Below the threshold the price doubles: 1 - 2 is clamped to 0.
	_game_state.consume_action_resources("prepare_sample")
	_check_equal(
		"a critical resource doubles the price of the action it gates",
		_game_state.resource_amount("RES_FUEL"),
		0
	)
	_check_equal(
		"the doubled price is recorded in the daily spending",
		_game_state.resource_spent_today("RES_FUEL"),
		9
	)
	_check_equal(
		"a depleted resource is reported as depleted",
		_game_state.resource_state("RES_FUEL"),
		"depleted"
	)

	# A depleted resource refuses the action it gates.
	_check(
		"a depleted resource blocks the action it gates",
		not _game_state.can_afford_kind("prepare_sample")
	)

	# The decay of the town is applied when a day passes.
	_game_state.reset()
	_game_state.tick = 95
	_game_state.advance_steps(1)
	_check_equal("the clock crossed into Day 2", _game_state.tick, 96)
	_check_equal(
		"the food decays by two units when the day crosses",
		_game_state.resource_amount("RES_FOOD"),
		22
	)
	_check_equal(
		"the medicine decays by one unit when the day crosses",
		_game_state.resource_amount("RES_MEDICINE"),
		9
	)
	_check_equal(
		"the fuel decays by one unit when the day crosses",
		_game_state.resource_amount("RES_FUEL"),
		7
	)
	_check_equal(
		"the daily spending is reset when the day crosses",
		_game_state.resource_spent_today("RES_FOOD"),
		0
	)

	# The decay happens once per crossing, never per tick.
	_game_state.advance_steps(95)
	_check_equal("the clock is back at the end of Day 2", _game_state.tick, 191)
	_check_equal(
		"no second decay happened inside the day",
		_game_state.resource_amount("RES_FOOD"),
		22
	)

	# The state of the provisions is published as a whole.
	var state: Dictionary = _game_state.resources_state()
	_check("the published state holds the amounts", state.has("amounts"))
	_check("the published state holds the daily spending", state.has("spent_today"))
	_check("the published state holds the state of every resource", state.has("states"))
	_check_equal(
		"the published amount of the food is the current one",
		state["amounts"]["RES_FOOD"],
		_game_state.resource_amount("RES_FOOD")
	)

	_game_state.reset()

#endregion


#region The irreversible death of a villager

## Check the GDScript mirror of the death of a villager.
##
## The death is a fact of the world read from the content document, never a
## decision of the player. The tick of the death is the tick at which the
## villager is **already gone**: with `deceased_at_tick = 192` the villager
## is alive at tick 191 and dead at tick 192.
##
## The design decision D33 forbids a counter of the dead: the player only
## sees the empty space where somebody used to stand.
func _test_death() -> void:
	print("")
	print("-- death --")

	var baker: Dictionary = _content_db.npc("NPC_BAKER")
	_check("the content declares the death of a villager", baker.has("deceased_at_tick"))
	_check_equal("the villager dies at the tick 192", int(baker.get("deceased_at_tick", -1)), 192)
	_check_equal(
		"the cause of the death is the plague",
		String(baker.get("death_cause", "")),
		"plague_fever"
	)

	# The villager is alive the tick before the death...
	_check(
		"the villager is alive the tick before the death",
		not _game_state.is_dead("NPC_BAKER", 191)
	)
	# ... and dead on the tick of the death.
	_check(
		"the villager is dead on the tick of the death",
		_game_state.is_dead("NPC_BAKER", 192)
	)
	_check(
		"the death is irreversible",
		_game_state.is_dead("NPC_BAKER", 480)
	)

	# A villager without a death is alive for the whole cycle.
	_check(
		"a villager without a death stays alive",
		not _game_state.is_dead("NPC_MILLER", 480)
	)
	_check(
		"an unknown villager is not dead",
		not _game_state.is_dead("NPC_GHOST", 480)
	)

	# The report of the deaths is empty before the death and grows after it.
	_check_equal("no villager has died before the tick 192", _game_state.deaths(191).size(), 0)
	_check_equal("one villager has died at the tick 192", _game_state.deaths(192).size(), 1)
	_check_equal(
		"the report names the dead villager",
		_game_state.deaths(192).has("NPC_BAKER"),
		true
	)
	_check_equal(
		"the report carries the tick of the death",
		int(_game_state.deaths(192)["NPC_BAKER"]),
		192
	)

	# The agent of the dead villager is not placed and not drawn.
	var agent: NpcAgent = NpcAgent.new()
	agent.name = "Npc_NPC_BAKER"
	root.add_child(agent)
	agent.build(baker)

	_check("the living villager is alive", agent.is_alive)
	_check("the living villager is visible", agent.visible)
	agent.refresh(191)
	_check("the villager is alive the tick before the death", agent.is_alive)
	_check("the villager is visible the tick before the death", agent.visible)

	agent.refresh(192)
	_check("the villager is dead on the tick of the death", not agent.is_alive)
	_check("the villager is not drawn any more", not agent.visible)
	_check("the villager is not interactable any more", not agent.is_interactable)

	# The player cannot even target a dead villager.
	_check(
		"a dead villager is not a target of the player",
		Player.npc_tile_at(baker, 192) == Vector2i(-1, -1),
		"the tile of the dead villager is %s" % str(Player.npc_tile_at(baker, 192))
	)

	agent.queue_free()

#endregion
