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

## Number of days of the playable cycle. Mirrors `core.time.CYCLE_DAYS`.
const CYCLE_DAYS: int = 5

## Number of ticks in the full playable cycle. Mirrors `core.time.TOTAL_TICKS`.
const TOTAL_TICKS: int = 480

## Current tick of the run, in `[0, TOTAL_TICKS]`.
var tick: int = 0

## Decisions taken so far, in chronological order.
##
## Each entry is a dictionary with the keys `kind`, `target`, `tick` and
## `payload`, mirroring `core.state.Decision`.
var decisions: Array[Dictionary] = []

## Provisions of the town, keyed by resource id.
##
## Mirrors `core.resources.ResourceState`. The amounts are the ones the
## simulation core decided on: this autoload only mirrors the consumption so
## that the HUD can show them.
var _resources: Dictionary = {}

## Whether the provisions were already read from the content document.
var _resources_loaded: bool = false

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


#region Resources (mirror of core/resources.py)

## Return the provisions of the town.
##
## The provisions are read from the content document **lazily**: the content
## database may not be loaded yet when this autoload enters the tree, so the
## lookup happens on the first access instead of in `_ready()`.
##
## @return The resource documents, keyed by resource id.
var resources: Dictionary:
	get:
		_ensure_resources()
		return _resources


## Read the provisions from the content document, once.
func _ensure_resources() -> void:
	if _resources_loaded:
		return
	_resources_loaded = true
	var content_db: Node = AutoloadRef.content_db(self)
	if content_db == null:
		return
	load_resources(content_db.resources)


## Load the provisions of the town from the exported content document.
##
## The amounts are the ones the content declares: this is a mirror of the
## simulation core, which remains the source of truth. The autoload only
## needs them to display the provisions and to mirror their consumption.
##
## @param specs The `resources` array of the exported content document.
func load_resources(specs: Array) -> void:
	_resources.clear()
	_resources_loaded = true
	for raw in specs:
		if not (raw is Dictionary):
			continue
		var resource_id: String = String(raw.get("id", ""))
		if resource_id.is_empty():
			continue
		_resources[resource_id] = {
			"id": resource_id,
			"label": String(raw.get("label", resource_id)),
			"initial": int(raw.get("initial", 0)),
			"per_action": int(raw.get("per_action", 0)),
			"critical_at": int(raw.get("critical_at", 0)),
			"amount": int(raw.get("initial", 0)),
		}


## Return the amount held of a resource.
##
## @param resource_id Id of the resource.
## @return The amount held, or 0 when the resource is not tracked.
func resource_amount(resource_id: String) -> int:
	if not _resources.has(resource_id):
		return 0
	return int(_resources[resource_id].get("amount", 0))


## Check whether a resource is in a critical state.
##
## A resource is critical when its amount fell strictly below the
## `critical_at` threshold of its specification, exactly like
## `core.resources.ResourceState.is_critical`.
##
## @param resource_id Id of the resource.
## @return `true` when the resource is in crisis.
func is_resource_critical(resource_id: String) -> bool:
	if not _resources.has(resource_id):
		return false
	var spec: Dictionary = _resources[resource_id]
	return resource_amount(resource_id) < int(spec.get("critical_at", 0))


## Return the ids of the resources whose exhaustion puts the town in crisis.
##
## @return The resource ids in crisis, sorted.
func resource_crisis() -> PackedStringArray:
	_ensure_resources()
	var crisis: PackedStringArray = PackedStringArray()
	for resource_id in _resources.keys():
		if is_resource_critical(String(resource_id)):
			crisis.append(String(resource_id))
	crisis.sort()
	return crisis


## Check whether the town can pay for one more action.
##
## Mirrors `core.resources.can_afford`.
##
## @return `true` when every tracked resource covers the cost of one action.
func can_afford_action() -> bool:
	_ensure_resources()
	for resource_id in _resources.keys():
		var spec: Dictionary = _resources[resource_id]
		if resource_amount(String(resource_id)) < int(spec.get("per_action", 0)):
			return false
	return true


## Consume the provisions of one action.
##
## Mirrors `core.resources.consume`: the amounts are clamped to zero, so a
## resource that cannot cover its cost ends up depleted rather than negative.
##
## @return The ids of the resources that ran out.
func consume_action_resources() -> PackedStringArray:
	_ensure_resources()
	var depleted: PackedStringArray = PackedStringArray()
	for resource_id in _resources.keys():
		var key: String = String(resource_id)
		var spec: Dictionary = _resources[key]
		var remaining: int = resource_amount(key) - int(spec.get("per_action", 0))
		spec["amount"] = maxi(0, remaining)
		_resources[key] = spec
		if int(spec["amount"]) <= 0:
			depleted.append(key)
	depleted.sort()
	return depleted

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
## The provisions of the town are consumed **per action**, not per tick:
## waiting burns time without drawing on the stores, but every real action
## pays its cost. An action the town cannot afford is refused and consumes
## neither the tick nor the provisions, mirroring
## `core.world.InsufficientResourcesError`.
##
## @param kind Kind of action, e.g. `"talk"`.
## @param target Id of the NPC or object the action refers to.
## @param payload Extra data of the decision.
## @return The derived world state at the new tick.
func advance(kind: String, target: String = "", payload: Dictionary = {}) -> Dictionary:
	if tick >= TOTAL_TICKS:
		push_warning("cannot advance past the cycle end (tick %d)" % TOTAL_TICKS)
		return _state

	if not can_afford_action():
		push_warning("the town cannot afford this action")
		return _state

	apply_decision(kind, target, payload)
	consume_action_resources()
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
	_ensure_resources()
	for resource_id in _resources.keys():
		var spec: Dictionary = _resources[resource_id]
		spec["amount"] = int(spec.get("initial", 0))
		_resources[resource_id] = spec
	_rederive()
	decisions_changed.emit(decisions)
	tick_changed.emit(tick, _state)

#endregion
