extends RefCounted
class_name ActionRequest
## A request from the player to act on the world.
##
## The player **consults** the world to find out whether an interaction is
## possible, but it never *decides* that it is: it emits a request, and the
## game state turns that request into a decision. This keeps the golden rule
## intact — Godot captures input, the simulation core decides.
##
## A request carries the kind of action, the target it refers to and an
## optional payload. The kind vocabulary is the one used by the Python core:
##
## [codeblock]
## talk              talk to an NPC
## examine           inspect an object
## report_symptom    report a symptom to an NPC
## move              move into a zone
## wait              burn a tick on purpose
## [/codeblock]

## Kind of the action, e.g. `"talk"`.
var kind: String = ""

## Id of the NPC or object the action refers to.
var target: String = ""

## Extra data of the action, e.g. `{"symptom": "SYM_NUMBNESS"}`.
var payload: Dictionary = {}


## Build an action request.
##
## @param action_kind Kind of the action, e.g. `"talk"`.
## @param action_target Id of the NPC or object the action refers to.
## @param action_payload Extra data of the action.
func _init(action_kind: String = "", action_target: String = "", action_payload: Dictionary = {}) -> void:
	kind = action_kind
	target = action_target
	payload = action_payload.duplicate(true)


## Return a copy of this request.
##
## @return A new request holding the same values.
func duplicate_request() -> ActionRequest:
	return ActionRequest.new(kind, target, payload)


## Return the request as a plain dictionary.
##
## @return The request as a dictionary with the keys `kind`, `target` and `payload`.
func to_dictionary() -> Dictionary:
	return {
		"kind": kind,
		"target": target,
		"payload": payload.duplicate(true),
	}
