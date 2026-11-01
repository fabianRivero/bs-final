extends CanvasLayer
class_name DialogueUi
## The panel that shows a conversation with an NPC.
##
## The F3 prototype only proves that the panel opens, shows the name of the NPC
## and closes again. The real dialogue — the options, the conditions and the
## symptom reports — belongs to F4, together with the dialogue resolution of
## `core/dialogue.py`.
##
## The panel never decides which option is available: it asks the simulation
## core. This is the placeholder for that wiring.
##
## The panel is a [CanvasLayer], so it always covers the whole viewport
## whatever the camera of the world does.

## Emitted when the player closes the dialogue.
signal closed

## The panel that holds the conversation.
var _panel: PanelContainer = null

## The full-rect control holding the panel.
var _root: Control = null

## The label showing the name of the speaker.
var _name_label: Label = null

## The label showing the text of the conversation.
var _text_label: Label = null

## The id of the NPC being talked to.
var _speaker_id: String = ""


func _ready() -> void:
	## Build the panel, hidden until a conversation starts.
	name = "DialogueUi"
	layer = 20
	_root = Control.new()
	_root.name = "Root"
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)
	_build_panel()
	visible = false


## Build the layout of the dialogue panel.
func _build_panel() -> void:
	_panel = PanelContainer.new()
	_panel.name = "Panel"
	_panel.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	_panel.position = Vector2(60, -200)
	_panel.custom_minimum_size = Vector2(840, 160)
	_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(_panel)

	var column: VBoxContainer = VBoxContainer.new()
	column.name = "Column"
	_panel.add_child(column)

	_name_label = Label.new()
	_name_label.name = "SpeakerLabel"
	_name_label.text = ""
	_name_label.add_theme_font_size_override("font_size", 16)
	_name_label.add_theme_color_override("font_color", Color(0.98, 0.85, 0.55))
	_name_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_name_label)

	_text_label = Label.new()
	_text_label.name = "TextLabel"
	_text_label.text = ""
	_text_label.add_theme_font_size_override("font_size", 14)
	_text_label.add_theme_color_override("font_color", Color(0.93, 0.91, 0.85))
	_text_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text_label.custom_minimum_size = Vector2(800, 60)
	_text_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_text_label)

	var hint: Label = Label.new()
	hint.name = "HintLabel"
	hint.text = "SPACE  close"
	hint.add_theme_font_size_override("font_size", 11)
	hint.add_theme_color_override("font_color", Color(0.7, 0.68, 0.62))
	hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(hint)


## Open a conversation with an NPC.
##
## @param npc_id The id of the NPC being talked to.
## @param text The text of the conversation. The F3 prototype uses a
##        placeholder; F4 resolves it from the dialogue content.
func open_for(npc_id: String, text: String = "") -> void:
	_speaker_id = npc_id
	var content_db: Node = AutoloadRef.content_db(self)
	var npc: Dictionary = {}
	if content_db != null:
		npc = content_db.npc(npc_id)
	var speaker_name: String = String(npc.get("name", npc_id))
	if _name_label != null:
		_name_label.text = speaker_name
	if _text_label != null:
		_text_label.text = text if not text.is_empty() else (
			"[The conversation system is implemented in F4.]"
		)
	visible = true


## Close the conversation.
func close() -> void:
	visible = false
	_speaker_id = ""
	closed.emit()


## Return the id of the NPC being talked to.
##
## @return The speaker id, or an empty string when no conversation is open.
func speaker_id() -> String:
	return _speaker_id


## Handle the input of the dialogue panel.
##
## @param event The input event to inspect.
func _unhandled_input(event: InputEvent) -> void:
	if not visible:
		return
	if event.is_echo() or not event.is_pressed():
		return
	if event.is_action_pressed("interact"):
		close()
