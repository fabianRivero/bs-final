extends SceneTree

## Cross-check: the local GDScript derive() must produce the same flags as
## core/state.py in Python for the same (tick, decisions).
## Reference output produced by core/state.py:
##   decided:examine, decided:move, decided:report_symptom, decided:talk,
##   examined:OBJ_HERBAL, knows:source:SRC_HERBAL, knows:symptom:SYM_SPOTS,
##   talked:NPC_MARTA, talked:NPC_TOMAS, visited:ZONE_PORT
##   symptoms_known: ('SYM_SPOTS',)

func _initialize() -> void:
	var decisions: Array[Dictionary] = [
		{"kind": "talk", "target": "NPC_MARTA", "tick": 0, "payload": {}},
		{"kind": "report_symptom", "target": "NPC_MARTA", "tick": 5, "payload": {"symptom": "SYM_SPOTS"}},
		{"kind": "examine", "target": "OBJ_HERBAL", "tick": 12, "payload": {}},
		{"kind": "move", "target": "ZONE_PORT", "tick": 20, "payload": {}},
		{"kind": "talk", "target": "NPC_TOMAS", "tick": 30, "payload": {"sets_flags": "knows:source:SRC_HERBAL"}},
	]
	var script: Script = load("res://autoload/game_state.gd")
	var state = script.new()

	var derived = script.derive(137, decisions)
	var flags: Array = derived.get("flags")
	flags.sort()
	print("GDSCRIPT derive(137):")
	for f in flags:
		print("   ", f)
	print("count: ", flags.size())

	state.decisions = decisions
	state._rederive()
	print("symptoms_known: ", state.symptoms_known())
	print("has_flag(talked:NPC_MARTA): ", state.has_flag("talked:NPC_MARTA"))
	print("has_flag(nope): ", state.has_flag("nope"))
	quit()
