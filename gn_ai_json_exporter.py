bl_info = {
    # 外掛基本資訊，會顯示在 Blender 的 Add-ons 清單中
    "name": "GN AI JSON Exporter",
    "author": "GitHub Copilot",
    "version": (1, 2, 0),
    "blender": (4, 5, 0),
    "location": "3D View / Geometry Nodes Editor > Sidebar > GN Exporter",
    "description": "Export Geometry Nodes to AI-readable JSON",
    "category": "Node",
}

import bpy
import json
import os


def _get_geometry_node_editor_tree(context):
    # 取得目前 Geometry Nodes Editor 正在編輯的節點樹
    space = getattr(context, "space_data", None)
    if not space or space.type != "NODE_EDITOR":
        return None

    if getattr(space, "tree_type", "") != "GeometryNodeTree":
        return None

    tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
    if not tree or getattr(tree, "bl_idname", "") != "GeometryNodeTree":
        return None

    return tree


def _get_active_object(context):
    # 取得目前作用中的物件
    return getattr(context, "active_object", None)


def _get_geometry_nodes_modifiers(obj):
    # 從物件身上篩出所有有效的 Geometry Nodes Modifier
    if obj is None:
        return []

    return [modifier for modifier in obj.modifiers if modifier.type == "NODES" and modifier.node_group is not None]


def _modifier_items(self, context):
    # 提供 EnumProperty 使用的 Modifier 下拉選單項目
    obj = _get_active_object(context)
    modifiers = _get_geometry_nodes_modifiers(obj)

    if not modifiers:
        return [("NONE",
                 "無可用 Geometry Nodes",
                 "目前作用中物件沒有可導出的 Geometry Nodes Modifier")]

    return [(modifier.name, modifier.name, "") for modifier in modifiers]


def _get_modifier_node_tree(context, modifier_name):
    # 根據名稱找到要導出的 Geometry Nodes Modifier 與其 node tree
    obj = _get_active_object(context)
    modifiers = _get_geometry_nodes_modifiers(obj)

    if not modifiers:
        return None, None, None

    if modifier_name and modifier_name != "NONE":
        for modifier in modifiers:
            if modifier.name == modifier_name:
                return obj, modifier, modifier.node_group

    modifier = modifiers[0]
    return obj, modifier, modifier.node_group


def _serialize_value(value):
    # 將 Blender 物件值轉成可寫入 JSON 的 Python 基本型別
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, (list, tuple, set)):
        return [_serialize_value(item) for item in value]

    class_name = value.__class__.__name__

    if class_name in {"bpy_prop_array", "Vector", "Color", "Euler", "Quaternion"}:
        try:
            return [_serialize_value(item) for item in value]
        except Exception:
            pass

    if class_name == "Matrix":
        try:
            return [[_serialize_value(item) for item in row] for row in value]
        except Exception:
            pass

    if hasattr(value, "name"):
        try:
            return value.name
        except Exception:
            pass

    return str(value)


def _serialize_socket(socket):
    # 序列化單一 socket 的資訊
    data = {
        "name": socket.name,
        "identifier": getattr(socket, "identifier", ""),
        "type": getattr(socket, "type", ""),
        "bl_idname": getattr(socket, "bl_idname", ""),
        "is_linked": bool(socket.is_linked),
        "is_multi_input": bool(getattr(socket, "is_multi_input", False)),
    }

    if hasattr(socket, "default_value"):
        try:
            data["default_value"] = _serialize_value(socket.default_value)
        except Exception:
            pass

    return data


def _get_tree_key(tree):
    # 取得節點樹唯一識別，用來避免重複導出同一個 group tree
    try:
        return int(tree.as_pointer())
    except Exception:
        return id(tree)


def _serialize_node(node, group_file_map=None):
    # 序列化單一節點的資訊與其輸入輸出 socket
    data = {
        "name": node.name,
        "label": node.label,
        "type": node.type,
        "bl_idname": node.bl_idname,
        "location": [float(node.location.x), float(node.location.y)],
        "width": float(node.width),
        "height": float(node.height),
        "selected": bool(node.select),
        "muted": bool(node.mute),
        "hidden": bool(node.hide),
        "inputs": [_serialize_socket(socket) for socket in node.inputs],
        "outputs": [_serialize_socket(socket) for socket in node.outputs],
    }

    group_tree = getattr(node, "node_tree", None)
    if group_tree is not None:
        referenced_data = {
            "name": group_tree.name,
            "bl_idname": group_tree.bl_idname,
        }

        if group_file_map:
            group_file = group_file_map.get(_get_tree_key(group_tree))
            if group_file:
                referenced_data["export_file"] = group_file

        data["referenced_node_tree"] = referenced_data

    return data


def _serialize_link(link):
    # 序列化節點之間的連線資訊
    return {
        "from_node": link.from_node.name,
        "from_socket": link.from_socket.name,
        "to_node": link.to_node.name,
        "to_socket": link.to_socket.name,
    }


def _sanitize_filename(name):
    # 將檔名中不安全的字元替換成底線，避免輸出失敗
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
    return safe.strip("_") or "geometry_nodes"


def _collect_group_trees(tree, visited=None):
    # 遞迴收集此 tree 內所有被 group node 參照到的 GeometryNodeTree
    if visited is None:
        visited = {_get_tree_key(tree)}

    group_trees = []

    for node in tree.nodes:
        group_tree = getattr(node, "node_tree", None)
        if group_tree is None:
            continue

        if getattr(group_tree, "bl_idname", "") != "GeometryNodeTree":
            continue

        tree_key = _get_tree_key(group_tree)
        if tree_key in visited:
            continue

        visited.add(tree_key)
        group_trees.append(group_tree)
        group_trees.extend(_collect_group_trees(group_tree, visited))

    return group_trees


def _export_tree(tree, selected_only, group_file_map=None):
    # 匯出整棵樹，或只匯出目前選取的節點
    nodes = [node for node in tree.nodes if node.select] if selected_only else list(tree.nodes)

    if not nodes:
        nodes = list(tree.nodes)
        selection_mode = "all_nodes_fallback_no_selection"
    else:
        selection_mode = "selected_nodes" if selected_only else "all_nodes"

    selected_names = {node.name for node in nodes}

    links = [
        _serialize_link(link)
        for link in tree.links
        if link.from_node.name in selected_names and link.to_node.name in selected_names
    ]

    return {
        "name": tree.name,
        "bl_idname": tree.bl_idname,
        "selection_mode": selection_mode,
        "node_count": len(nodes),
        "link_count": len(links),
        "nodes": [_serialize_node(node, group_file_map) for node in nodes],
        "links": links,
    }


def _build_export_data(tree, source, obj, modifier, selected_only, group_file_map=None, export_role="main_tree", root_tree_name=None):
    # 組合單一 JSON 檔案的輸出內容
    data = {
        "format": "geometry_nodes_ai_json",
        "format_version": 2,
        "generator": "GN AI JSON Exporter",
        "blender_version": list(bpy.app.version),
        "source": source,
        "export_role": export_role,
        "object_name": obj.name if obj else None,
        "modifier_name": modifier.name if modifier else None,
        "tree": _export_tree(tree, selected_only, group_file_map),
    }

    if root_tree_name is not None:
        data["root_tree_name"] = root_tree_name

    return data


def _write_json_file(filepath, data):
    # 將資料寫成格式化 JSON 檔案
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


class GNEXPORTER_Props(bpy.types.PropertyGroup):
    # 外掛使用的自訂屬性，會掛在 Scene 上
    export_path: bpy.props.StringProperty(
        name="導出路徑",
        subtype="DIR_PATH",
        default=r"C:\Users\A1OT220601\Desktop\GN_Exporter\exports",
    )

    modifier_name: bpy.props.EnumProperty(
        name="GN Modifier",
        description="選擇要導出的 Geometry Nodes Modifier",
        items=_modifier_items,
    )

    export_selected_only: bpy.props.BoolProperty(
        name="僅導出目前選取節點",
        description="只在 Geometry Nodes Editor 中有效；若沒有選取節點會自動退回整棵樹",
        default=True,
    )

    export_group_trees: bpy.props.BoolProperty(
        name="另外導出 Group JSON",
        description="將 Group Node 參照的 Geometry Node Tree 另外輸出成獨立 JSON 檔案",
        default=True,
    )


class GNEXPORTER_OT_Export(bpy.types.Operator):
    # 執行 JSON 導出的主要操作
    bl_idname = "gn_exporter.export_json"
    bl_label = "執行導出"
    bl_description = "Export Geometry Nodes to AI-readable JSON"

    def execute(self, context):
        # 讀取使用者在面板中設定的參數
        props = context.scene.gn_exporter_props
        export_dir = bpy.path.abspath(props.export_path).strip()

        if not export_dir:
            self.report({"ERROR"}, "請先設定導出路徑")
            return {"CANCELLED"}

        editor_tree = _get_geometry_node_editor_tree(context)
        obj = None
        modifier = None
        tree = None
        selected_only = False
        source = ""

        if editor_tree is not None:
            # 如果目前在 Geometry Nodes Editor，就直接導出正在編輯的樹
            tree = editor_tree
            selected_only = props.export_selected_only
            source = "geometry_node_editor"
        else:
            # 否則改由作用中物件上的 Geometry Nodes Modifier 匯出
            obj, modifier, tree = _get_modifier_node_tree(context, props.modifier_name)
            if tree is None:
                self.report({"ERROR"}, "找不到可導出的 Geometry Nodes Tree")
                return {"CANCELLED"}
            selected_only = False
            source = "modifier_panel"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except Exception as exc:
            self.report({"ERROR"}, f"無法建立導出資料夾: {exc}")
            return {"CANCELLED"}

        # 用物件名、Modifier 名、Tree 名組出主檔輸出檔名
        if obj and modifier:
            filename_base = f"{obj.name}_{modifier.name}_{tree.name}"
        else:
            filename_base = tree.name

        main_stem = _sanitize_filename(filename_base)
        main_filename = f"{main_stem}.json"
        main_filepath = os.path.join(export_dir, main_filename)

        # 收集所有 group tree，並先分配各自的輸出檔名
        group_trees = _collect_group_trees(tree) if props.export_group_trees else []
        group_file_map = {}

        for index, group_tree in enumerate(group_trees, start=1):
            group_filename = f"{main_stem}__group_{index:02d}_{_sanitize_filename(group_tree.name)}.json"
            group_file_map[_get_tree_key(group_tree)] = group_filename

        # 組合主體 JSON
        data = _build_export_data(
            tree=tree,
            source=source,
            obj=obj,
            modifier=modifier,
            selected_only=selected_only,
            group_file_map=group_file_map,
            export_role="main_tree",
        )

        if group_trees:
            data["group_exports"] = [
                {
                    "tree_name": group_tree.name,
                    "file": group_file_map[_get_tree_key(group_tree)],
                }
                for group_tree in group_trees
            ]
            data["group_export_count"] = len(group_trees)

        try:
            _write_json_file(main_filepath, data)

            # 另外導出每個 group tree 的獨立 JSON
            for group_tree in group_trees:
                group_data = _build_export_data(
                    tree=group_tree,
                    source="group_node_tree",
                    obj=obj,
                    modifier=modifier,
                    selected_only=False,
                    group_file_map=group_file_map,
                    export_role="group_tree",
                    root_tree_name=tree.name,
                )

                group_data["group_file"] = group_file_map[_get_tree_key(group_tree)]

                group_filepath = os.path.join(export_dir, group_file_map[_get_tree_key(group_tree)])
                _write_json_file(group_filepath, group_data)
        except Exception as exc:
            self.report({"ERROR"}, f"寫入 JSON 失敗: {exc}")
            return {"CANCELLED"}

        if group_trees:
            self.report({"INFO"}, f"已導出: {main_filepath}，另含 {len(group_trees)} 個 Group JSON")
        else:
            self.report({"INFO"}, f"已導出: {main_filepath}")

        return {"FINISHED"}


class GNEXPORTER_PT_NodeEditorPanel(bpy.types.Panel):
    # 顯示在 Geometry Nodes Editor 側邊欄的面板
    bl_label = "GN Exporter"
    bl_idname = "GNEXPORTER_PT_node_editor_panel"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "GN Exporter"

    @classmethod
    def poll(cls, context):
        # 只有在 Geometry Nodes Editor 中才顯示此面板
        space = getattr(context, "space_data", None)
        return bool(space and space.type == "NODE_EDITOR" and getattr(space, "tree_type", "") == "GeometryNodeTree")

    def draw(self, context):
        # 繪製節點編輯器中的 UI
        layout = self.layout
        props = context.scene.gn_exporter_props

        layout.prop(props, "export_path")
        layout.prop(props, "export_selected_only")
        layout.prop(props, "export_group_trees")
        layout.operator("gn_exporter.export_json", icon="EXPORT")


class GNEXPORTER_PT_View3DPanel(bpy.types.Panel):
    # 顯示在 3D View 側邊欄的面板
    bl_label = "GN Exporter"
    bl_idname = "GNEXPORTER_PT_view3d_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GN Exporter"

    def draw(self, context):
        # 繪製 3D 視窗中的 UI
        layout = self.layout
        props = context.scene.gn_exporter_props
        obj = _get_active_object(context)
        modifiers = _get_geometry_nodes_modifiers(obj)

        layout.prop(props, "export_path")
        layout.prop(props, "export_group_trees")

        if modifiers:
            # 若有 Geometry Nodes Modifier，顯示選擇與導出按鈕
            layout.prop(props, "modifier_name")
            layout.operator("gn_exporter.export_json", icon="EXPORT")
        else:
            # 若沒有可用 Modifier，顯示提示訊息
            layout.label(text="目前作用中物件沒有可導出的 GN Modifier", icon="INFO")


# Blender 要註冊的類別清單
classes = (
    GNEXPORTER_Props,
    GNEXPORTER_OT_Export,
    GNEXPORTER_PT_NodeEditorPanel,
    GNEXPORTER_PT_View3DPanel,
)


def register():
    # 啟用外掛時註冊所有類別，並把屬性掛到 Scene
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.gn_exporter_props = bpy.props.PointerProperty(type=GNEXPORTER_Props)


def unregister():
    # 停用外掛時移除屬性並反向解除註冊類別
    del bpy.types.Scene.gn_exporter_props

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    # 直接執行此檔時，自動註冊外掛
    register()