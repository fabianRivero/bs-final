extends Node
## Autoload that owns the run state and derives the world from it.
##
## The world is never stored. It is a **pure function** of two inputs:
##
## [codeblock]
## WorldState = derive(tick, decisions)
## [/codeblock]
##
## This autoload is the GDScript mirror of `core/state.py`. It holds the tick
## and the list of decisions, and recomputes everything else on demand.
##
## [b]Parity with the Python core.[/b]
##
## The flag derivation below is a line-by-line translation of
## `core.state._flag_for_decision` and `core.state.derive`. The vocabulary is
## identical and must never drift:
##
## [codeblock]
## decided:<kind>            any decision of that kind
## talked:<target>           a "talk" decision targeting that NPC
## examined:<target>         an "examine" decision targeting that object
## visited:<zone>            a "move" decision into that zone
## knows:symptom:<id>        a "report_symptom" decision
## <explicit>                the "sets_flags" key of the decision payload
## [/codeblock]
##
## The calendar triple follows `core.time.to_datetime`: four consecutive ticks
## share the same `(day, hour)` pair, so the minute is part of the value.
## `tools/parity_check.py` compares the two implementations tick by tick.
##
## The golden rule of the project holds here: Godot never *decides* anything.
## It records what the player did, derives the consequences of that record, and
## publishes them.

## Emitted whenever the tick changes, after the derived state has been recomputed.
##
## Every system in the game subscribes to this signal. Nobody polls "what is in
## this tick?" — the state is pushed.
signal tick_changed(tick: int, state: Dictionary)

## Emitted whenever the set of decisions changes.
signal decisions_changed(decisions: Array)

## Emitted when the run reaches the closing tick of the cycle.
signal cycle_closed(tick: int)

## Number of minutes of in-game time represented by a single tick.
## Mirrors `core.time.MINUTES_PER_TICK`.
const MINUTES_PER_TICK: int = 15

## Number of ticks in a full in-game day. Mirrors `core.time.TICKS_PER_DAY`.
const TICKS_PER_DAY: int = 96

## Number of ticks in the full playable cycle. Mirrors `core.time.TOTAL_TICKS`.
const TOTAL_TICKS: int = 288

## Current tick of the run, in `[0, TOTAL_TICKS]`.
var tick: int = 0

## Decisions taken so far, in chronological order.
##
## Each entry is a dictionary with the keys `kind`, `target`, `tick` and
## `payload`, mirroring `core.state.Decision`.
var decisions: Array[Dictionary] = []

## Cached derived state, recomputed on every mutation.
var _state: Dictionary = {}


func _ready() -> void:
	## Initialise the derived state so the very first `tick_changed` listener
	## sees a consistent world.
	AutoloadRef.register("GameState", self)
	_rederive()


#region Calendar (mirror of core/time.py)

## Convert a tick into a `(day, hour, minute)` calendar instant.
##
## The triple is lossless: every tick of the cycle maps to exactly one instant
## and every instant maps back to exactly one tick.
##
## @param tick_index Tick index in `[0, TOTAL_TICKS]`.
## @return The instant as a dictionary with the keys `day`, `hour` and `minute`.
static func to_datetime(tick_index: int) -> Dictionary:
	var day: int = tick_index / TICKS_PER_DAY + 1
	var minutes_of_day: int = (tick_index % TICKS_PER_DAY) * MINUTES_PER_TICK
	return {
		"day": day,
		"hour": minutes_of_day / 60,
		"minute": minutes_of_day % 60,
	}


## Render a tick as a human readable clock label.
##
## @param tick_index Tick index in `[0, TOTAL_TICKS]`.
## @return A string of the form `"Day 1 07:15"`.
static func format_clock(tick_index: int) -> String:
	var instant: Dictionary = to_datetime(tick_index)
	return "Day %d %02d:%02d" % [instant["day"], instant["hour"], instant["minute"]]

#endregion


#region Derivation (mirror of core/state.py)

## Compute the flags raised by a single decision.
##
## This is the GDScript mirror of `core.state._flag_for_decision`. The order of
## the returned array differs from Python's tuple on purpose: the flags live in
## a set on the Python side, so the order was never observable there. The set
## of flags is what must match, and it does.
##
## @param decision The decision to inspect.
## @return The names of the flags raised by the decision.
static func flags_for_decision(decision: Dictionary) -> PackedStringArray:
	var flags: PackedStringArray = PackedStringArray()
	var kind: String = String(decision.get("kind", ""))
	flags.append("decided:%s" % kind)

	var target: String = String(decision.get("target", ""))
	match kind:
		"talk":
			if not target.is_empty():
				flags.append("talked:%s" % target)
		"examine":
			if not target.is_empty():
				flags.append("examined:%s" % target)
		"report_symptom":
			var payload: Dictionary = decision.get("payload", {})
			var symptom = payload.get("symptom", null)
			if symptom != null:
				flags.append("knows:symptom:%s" % str(symptom))
		"move":
			if not target.is_empty():
				flags.append("visited:%s" % target)

	var explicit = decision.get("payload", {}).get("sets_flags", null)
	if explicit is String:
		flags.append(String(explicit))
	elif explicit is Array or explicit is PackedStringArray:
		for name in explicit:
			flags.append(str(name))

	return flags


## Derive the world state from a tick and the decisions taken.
##
## The function is **pure**: it does not mutate its arguments and it does not
## read the system clock. It is the GDScript mirror of `core.state.derive`.
##
## @param tick_index Tick the state describes, in `[0, TOTAL_TICKS]`.
## @param decision_list Decisions taken so far, in chronological order.
## @return The derived world state as a dictionary.
static func derive(tick_index: int, decision_list: Array) -> Dictionary:
	var instant: Dictionary = to_datetime(tick_index)

	var flag_set: Dictionary = {}
	for decision in decision_list:
		for flag_name in flags_for_decision(decision):
			flag_set[flag_name] = true

	var flags: PackedStringArray = PackedStringArray()
	for flag_name in flag_set.keys():
		flags.append(String(flag_name))
	flags.sort()

	return {
		"tick": tick_index,
		"day": instant["day"],
		"hour": instant["hour"],
		"minute": instant["minute"],
		"decisions": decision_list.duplicate(true),
		"flags": flags,
	}


## Recompute and cache the derived state of the current run.
func _rederive() -> void:
	_state = derive(tick, decisions)


## Return the derived state of the current run.
##
## @return The derived world state as a dictionary.
func state() -> Dictionary:
	return _state


## Check whether a flag is active in the current derived state.
##
## @param name Name of the flag.
## @return `true` when the flag is active.
func has_flag(name: String) -> bool:
	return _state.get("flags", PackedStringArray()).has(name)


## Return the ids of the symptoms the player knows about.
##
## Mirrors `core.state.WorldState.symptoms_known`.
##
## @return The symptom ids, sorted and without duplicates.
func symptoms_known() -> PackedStringArray:
	var symptoms: PackedStringArray = PackedStringArray()
	var seen: Dictionary = {}
	for decision in decisions:
		if String(decision.get("kind", "")) != "report_symptom":
			continue
		var payload: Dictionary = decision.get("payload", {})
		if not payload.has("symptom"):
			continue
		var symptom_id: String = str(payload["symptom"])
		if seen.has(symptom_id):
			continue
		seen[symptom_id] = true
		symptoms.append(symptom_id)
	symptoms.sort()
	return symptoms

#endregion


#region Mutation

## Record a decision without moving the clock.
##
## Mirrors `core.world.WorldSim.apply`: this is the hook used by events and
## missions, which apply their effect at the tick they trigger.
##
## @param kind Kind of action, e.g. `"talk"`.
## @param target Id of the NPC or object the action refers to.
## @param payload Extra data of the decision.
## @return The derived world state after recording the decision.
func apply_decision(kind: String, target: String = "", payload: Dictionary = {}) -> Dictionary:
	decisions.append({
		"kind": kind,
		"target": target,
		"tick": tick,
		"payload": payload.duplicate(true),
	})
	_rederive()
	decisions_changed.emit(decisions)
	return _state


## Record a decision and move the clock forward by one tick.
##
## Mirrors `core.world.WorldSim.advance`. The clock is bounded: advancing past
## the closing tick of the cycle is refused, exactly like
## `core.time.ClockOverflowError`.
##
## @param kind Kind of action, e.g. `"talk"`.
## @param target Id of the NPC or object the action refers to.
## @param payload Extra data of the decision.
## @return The derived world state at the new tick.
func advance(kind: String, target: String = "", payload: Dictionary = {}) -> Dictionary:
	if tick >= TOTAL_TICKS:
		push_warning("cannot advance past the cycle end (tick %d)" % TOTAL_TICKS)
		return _state

	apply_decision(kind, target, payload)
	tick += 1
	_rederive()
	tick_changed.emit(tick, _state)
	if tick >= TOTAL_TICKS:
		cycle_closed.emit(tick)
	return _state


## Move the clock forward by a number of ticks without recording a decision.
##
## Used by the `advance_tick` action to let the player burn time on purpose.
##
## @param steps Number of ticks to advance. Must be non-negative.
## @return The derived world state at the new tick.
func advance_steps(steps: int = 1) -> Dictionary:
	var moved: int = 0
	while moved < steps and tick < TOTAL_TICKS:
		tick += 1
		moved += 1
	_rederive()
	tick_changed.emit(tick, _state)
	if tick >= TOTAL_TICKS:
		cycle_closed.emit(tick)
	return _state


## Reset the run to its initial state.
func reset() -> void:
	tick = 0
	decisions.clear()
	_rederive()
	decisions_changed.emit(decisions)
	tick_changed.emit(tick, _state)

#endregion
