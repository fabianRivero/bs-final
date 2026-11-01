extends Node2D
class_name NpcSprite
## The visual representation of an NPC.
##
## The sprite is the part of the NPC the player sees: a placeholder shape in
## the F3 prototype, a real animation in F4. It is kept apart from
## [NpcAgent] so that the art can be replaced without touching the logic that
## places the NPC in the world.

## Emitted when the activity of the NPC changes.
signal activity_changed(activity: String)

## The activity currently shown.
var activity: String = ""

## The name shown when the player looks at the NPC.
var display_name: String = ""

## The label drawn above the NPC.
var _label: Label = null

## The body of the sprite.
var _body: Node2D = null


## Build the sprite for an NPC.
##
## @param npc_data The NPC document read from the content database.
func build(npc_data: Dictionary) -> void:
	display_name = String(npc_data.get("name", ""))

	_body = Node2D.new()
	_body.name = "Body"
	add_child(_body)

	var shape: Polygon2D = Polygon2D.new()
	shape.name = "Shape"
	shape.color = Color(0.36, 0.52, 0.72)
	shape.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(20, 0.0),
		Vector2(20, 24),
		Vector2(0.0, 24.0),
	])
	shape.position = Vector2(-10, -22)
	_body.add_child(shape)

	var head: Polygon2D = Polygon2D.new()
	head.name = "Head"
	head.color = Color(0.93, 0.81, 0.66)
	head.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(14, 0.0),
		Vector2(14, 14),
		Vector2.ZERO, 14),
	])
	head.position = Vector2(-7, -36)
	_body.add_child(head)

	_label = Label.new()
	_label.name = "NameLabel"
	_label.text = display_name
	_label.position = Vector2(-40, -56)
	_label.size = Vector2(80, 16)
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.add_theme_font_size_override("font_size", 10)
	_label.add_theme_color_override("font_color", Color(0.95, 0.93, 0.85))
	_label.add_theme_color_override("font_outline_color", Color(0.0, 0.0, 0.0))
	_label.add_theme_constant_override("outline_size", 3)
	add_child(_label)


## Show a different activity on the sprite.
##
## @param new_activity The activity the NPC performs now.
func set_activity(new_activity: String) -> void:
	if new_activity == activity:
		return
	activity = new_activity
	activity_changed.emit(activity)
