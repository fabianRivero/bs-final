extends Node2D
## The playable scene: the world, the player, the NPCs and the HUD.
##
## The scene is minimal on purpose. Everything below the root node is built in
## code, which keeps the scene file trivial and makes the flow readable in one
## place.
##
## [b]The flow.[/b]
##
## [codeblock]
## input -> player checks interactivity (a query, not a decision)
##       -> emits an ActionRequest
##       -> GameState records the decision and advances the tick
##       -> emits tick_changed
##       -> ContentDb repositions the NPCs, Lighting applies the phase,
##          the HUD updates the clock
## [/codeblock]
##
## Every system subscribes to `tick_changed`. Nobody asks "what is in this
## tick?".

## The world view hosting the zones.
var world_view: WorldView = null

## The player character.
var player: Player = null

## The HUD.
var hud: Hud = null

## The dialogue panel.
var dialogue_ui: DialogueUi = null

## The NPC agents of the world, keyed by NPC id.
var npc_agents: Dictionary = {}


func _ready() -> void:
	## Build the scene and connect the systems.
	_build_scene()
	_connect_systems()
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state != null:
		_on_tick_changed(int(game_state.tick), game_state.state())
	# The lighting autoload subscribes to the clock on its own, but the
	# overlay belongs to this scene, so the phase is applied once more here.
	_apply_lighting(int(game_state.tick) if game_state != null else 0)


## Apply the lighting phase of a tick to the overlay of this scene.
##
## @param tick_index The tick whose phase is applied.
func _apply_lighting(tick_index: int) -> void:
	var lighting: Node = AutoloadRef.lighting(self)
	if lighting == null:
		return
	lighting.apply_phase(tick_index)
	lighting.refresh_overlay(self)


## Build the hierarchy of the playable scene.
func _build_scene() -> void:
	world_view = WorldView.new()
	world_view.name = "WorldView"
	add_child(world_view)

	player = Player.new()
	player.name = "Player"
	world_view.add_child(player)
	world_view.set_player(player)

	_load_zone()

	_build_npcs()

	hud = Hud.new()
	add_child(hud)

	dialogue_ui = DialogueUi.new()
	add_child(dialogue_ui)


## Load the playable zone into the world view.
##
## The F3 prototype ships a single playable zone, and its id is read from the
## content document rather than being hard-coded.
func _load_zone() -> void:
	var content_db: Node = AutoloadRef.content_db(self)
	if content_db == null:
		return
	var zone_id: String = content_db.first_zone_id()
	if zone_id.is_empty():
		push_warning("Game: the content document holds no zone to play.")
		return
	world_view.load_zone(content_db.zone(zone_id))


## Build one agent per NPC of the content document.
func _build_npcs() -> void:
	npc_agents.clear()
	var content_db: Node = AutoloadRef.content_db(self)
	if content_db == null:
		return
	for npc_id in content_db.npcs.keys():
		var agent: NpcAgent = NpcAgent.new()
		agent.name = "Npc_%s" % npc_id
		world_view.add_child(agent)
		agent.build(content_db.npc(String(npc_id)))
		npc_agents[String(npc_id)] = agent


## Connect the signals of the systems.
func _connect_systems() -> void:
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state != null:
		game_state.tick_changed.connect(_on_tick_changed)
	player.action_requested.connect(_on_action_requested)


## React to a tick change published by the game state.
##
## @param tick_index The new tick.
## @param _state The derived world state at the new tick.
func _on_tick_changed(tick_index: int, _state: Dictionary) -> void:
	for npc_id in npc_agents.keys():
		var agent: NpcAgent = npc_agents[npc_id]
		if is_instance_valid(agent):
			agent.refresh(tick_index)


## Handle an action request emitted by the player.
##
## The request is the player's *offer*. The game state turns it into a
## decision and advances the clock; the dialogue panel shows the placeholder
## conversation until F4 wires the real one.
##
## @param request The request emitted by the player.
func _on_action_requested(request: ActionRequest) -> void:
	if request.kind == "talk":
		dialogue_ui.open_for(request.target)
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state != null:
		game_state.advance(request.kind, request.target, request.payload)


## Handle the input that belongs to the scene rather than to a system.
##
## @param event The input event to inspect.
func _unhandled_input(event: InputEvent) -> void:
	if event.is_echo() or not event.is_pressed():
		return
	if event.is_action_pressed("advance_tick"):
		var game_state: Node = AutoloadRef.game_state(self)
		if game_state != null:
			game_state.advance_steps(1)
