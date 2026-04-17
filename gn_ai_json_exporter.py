bl_info = {
    # 外掛基本資訊，會顯示在 Blender 的 Add-ons 清單中
    "name": "GN AI JSON Exporter",
    "author": "GitHub Copilot",
    "version": (1, 5, 0),
    "blender": (4, 5, 0),
    "location": "3D View / Geometry Nodes Editor > Sidebar > GN Exporter",
    "description": "Export Geometry Nodes to AI-readable JSON",
    "category": "Node",
}

import bpy
import json
import os


SUPPORTED_BUILD_FORMAT_VERSION = 3


INTERFACE_SOCKET_TYPE_MAP = {
    "FLOAT": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "BOOLEAN": "NodeSocketBool",
    "VECTOR": "NodeSocketVector",
    "ROTATION": "NodeSocketRotation",
    "MATRIX": "NodeSocketMatrix",
    "STRING": "NodeSocketString",
    "RGBA": "NodeSocketColor",
    "COLOR": "NodeSocketColor",
    "GEOMETRY": "NodeSocketGeometry",
    "OBJECT": "NodeSocketObject",
    "COLLECTION": "NodeSocketCollection",
    "TEXTURE": "NodeSocketTexture",
    "IMAGE": "NodeSocketImage",
    "MATERIAL": "NodeSocketMaterial",
}


class _BuildImportState:
    # 管理遞迴 group 匯入時的快取、命名與循環檢查
    def __init__(self):
        self.import_stack = []
        self.group_cache = {}
        self.group_name_usage = {}


def _create_build_import_state():
    # 建立一次匯入流程共用的狀態物件
    return _BuildImportState()


def _as_bool(value, default=False):
    # 將常見 JSON 布林輸入統一轉成 bool
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False

    if value is None:
        return default

    return bool(value)


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


def _make_unique_group_name(base_name, import_state):
    # 避免遞迴匯入時建立出重名 group tree
    safe_base_name = (base_name or "Imported Group").strip() or "Imported Group"

    if import_state is None:
        return safe_base_name

    usage_count = import_state.group_name_usage.get(safe_base_name, 0)
    candidate_name = safe_base_name if usage_count == 0 else f"{safe_base_name}_{usage_count:02d}"

    while bpy.data.node_groups.get(candidate_name) is not None:
        usage_count += 1
        candidate_name = f"{safe_base_name}_{usage_count:02d}"

    import_state.group_name_usage[safe_base_name] = usage_count + 1
    return candidate_name


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


def _load_json_file(filepath):
    # 讀取 JSON 檔案內容
    with open(filepath, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_json_path(base_filepath, relative_filepath):
    # 將相對 JSON 路徑解析成實際檔案路徑
    if not relative_filepath:
        return None

    if os.path.isabs(relative_filepath):
        return relative_filepath

    if not base_filepath:
        return os.path.normpath(relative_filepath)

    return os.path.normpath(os.path.join(os.path.dirname(base_filepath), relative_filepath))


def _normalize_build_json_data(data, group_name=None):
    # 將簡化 build JSON 統一成 importer 可處理的完整格式
    if not isinstance(data, dict):
        raise ValueError("build JSON 資料格式必須是 object")

    if data.get("format") == "geometry_nodes_ai_build":
        normalized_data = dict(data)
    else:
        normalized_data = {
            "format": "geometry_nodes_ai_build",
            "format_version": data.get("format_version", 1),
            "nodes": data.get("nodes", []),
            "links": data.get("links", []),
        }

        for key in (
            "metadata",
            "clear_existing_nodes",
            "append_mode",
            "place_offset",
            "strict_mode",
            "interface",
            "description",
            "generator",
        ):
            if key in data:
                normalized_data[key] = data[key]

    if group_name and "group_name" not in normalized_data:
        normalized_data["group_name"] = group_name

    if "interface" not in normalized_data and "group_interface" in data:
        normalized_data["interface"] = data["group_interface"]

    return normalized_data


def _get_group_reference_key(base_filepath, node_data):
    # 為 group 來源建立穩定 key，供快取與防循環使用
    group_file = node_data.get("group_file")
    group_data = node_data.get("group_data")
    group_name = node_data.get("group_name")

    if group_file:
        resolved_path = _resolve_json_path(base_filepath, group_file)
        return ("group_file", os.path.normcase(resolved_path) if resolved_path else group_file)

    if isinstance(group_data, dict):
        try:
            normalized_group_data = _normalize_build_json_data(group_data, group_name=group_name)
            serialized = json.dumps(normalized_group_data, ensure_ascii=False, sort_keys=True)
        except Exception:
            serialized = str(group_data)

        return ("group_data", group_name or node_data.get("name") or "", serialized)

    if group_name:
        return ("group_name", group_name)

    return None


def _push_group_reference(import_state, reference_key):
    # 將目前 group 來源推入遞迴堆疊，若重複代表循環引用
    if import_state is None or reference_key is None:
        return

    if reference_key in import_state.import_stack:
        raise ValueError(f"偵測到循環 group 引用: {reference_key}")

    import_state.import_stack.append(reference_key)


def _pop_group_reference(import_state, reference_key):
    # 將目前 group 來源自遞迴堆疊移除
    if import_state is None or reference_key is None:
        return

    if import_state.import_stack and import_state.import_stack[-1] == reference_key:
        import_state.import_stack.pop()
        return

    try:
        import_state.import_stack.remove(reference_key)
    except ValueError:
        pass


def _clear_tree(tree):
    # 清空節點樹內現有節點
    for node in list(tree.nodes):
        tree.nodes.remove(node)


def _find_socket_by_name(sockets, socket_name):
    # 依名稱尋找 socket
    for socket in sockets:
        if socket.name == socket_name:
            return socket
    return None


def _find_socket_by_identifier(sockets, socket_identifier):
    # 依 identifier 尋找 socket
    for socket in sockets:
        if getattr(socket, "identifier", None) == socket_identifier:
            return socket
    return None


def _find_socket_by_index(sockets, socket_index):
    # 依 index 尋找 socket
    if not isinstance(socket_index, int):
        return None

    if socket_index < 0 or socket_index >= len(sockets):
        return None

    return sockets[socket_index]


def _find_socket(sockets, socket_reference):
    # 依 name / identifier / index 尋找 socket，支援舊版純字串格式
    if isinstance(socket_reference, dict):
        socket_identifier = socket_reference.get("identifier")
        if socket_identifier:
            socket = _find_socket_by_identifier(sockets, socket_identifier)
            if socket is not None:
                return socket

        if "index" in socket_reference:
            socket = _find_socket_by_index(sockets, socket_reference.get("index"))
            if socket is not None:
                return socket

        socket_name = socket_reference.get("name")
        if socket_name:
            return _find_socket_by_name(sockets, socket_name)

        return None

    if isinstance(socket_reference, int):
        return _find_socket_by_index(sockets, socket_reference)

    return _find_socket_by_name(sockets, socket_reference)


def _normalize_socket_reference(socket_reference):
    # 將 socket 參照統一成 dict 格式
    if isinstance(socket_reference, dict):
        return socket_reference

    if isinstance(socket_reference, int):
        return {"index": socket_reference}

    if socket_reference is None:
        return {}

    return {"name": socket_reference}


def _coerce_vector2(value, default=(0.0, 0.0)):
    # 將輸入轉成二維座標
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return float(default[0]), float(default[1])

    try:
        return float(value[0]), float(value[1])
    except Exception:
        return float(default[0]), float(default[1])


def _normalize_interface_item(in_out, item):
    # 將 interface item 標準化成可處理格式
    if not isinstance(item, dict):
        return None

    normalized_item = dict(item)
    normalized_item["in_out"] = (item.get("in_out") or in_out or "INPUT").upper()
    normalized_item["socket_type"] = (
        item.get("socket_type")
        or item.get("bl_socket_idname")
        or item.get("socket_idname")
        or INTERFACE_SOCKET_TYPE_MAP.get(str(item.get("type", "")).upper())
        or "NodeSocketFloat"
    )

    if not normalized_item.get("name"):
        normalized_item["name"] = "Socket"

    return normalized_item


def _normalize_interface_data(interface_data):
    # 支援多種 interface JSON 寫法
    if interface_data is None:
        return []

    normalized_items = []

    if isinstance(interface_data, dict):
        if isinstance(interface_data.get("items"), list):
            for item in interface_data["items"]:
                normalized_item = _normalize_interface_item(None, item)
                if normalized_item is not None:
                    normalized_items.append(normalized_item)
        else:
            for key, direction in (("inputs", "INPUT"), ("outputs", "OUTPUT")):
                for item in interface_data.get(key, []) or []:
                    normalized_item = _normalize_interface_item(direction, item)
                    if normalized_item is not None:
                        normalized_items.append(normalized_item)
    elif isinstance(interface_data, list):
        for item in interface_data:
            normalized_item = _normalize_interface_item(None, item)
            if normalized_item is not None:
                normalized_items.append(normalized_item)

    return normalized_items


def _set_socket_like_default_value(target, value):
    # 套用 interface item 或 socket 的 default value
    if not hasattr(target, "default_value"):
        return

    try:
        target.default_value = value
        return
    except Exception:
        pass

    try:
        default_value = target.default_value
        for index, item in enumerate(value):
            default_value[index] = item
    except Exception:
        pass


def _apply_interface_item_settings(interface_item, item_data):
    # 套用 interface socket 的常見設定
    if "description" in item_data and hasattr(interface_item, "description"):
        try:
            interface_item.description = item_data["description"]
        except Exception:
            pass

    if "hide_value" in item_data and hasattr(interface_item, "hide_value"):
        try:
            interface_item.hide_value = bool(item_data["hide_value"])
        except Exception:
            pass

    if "attribute_domain" in item_data and hasattr(interface_item, "attribute_domain"):
        try:
            interface_item.attribute_domain = item_data["attribute_domain"]
        except Exception:
            pass

    if "default_attribute_name" in item_data and hasattr(interface_item, "default_attribute_name"):
        try:
            interface_item.default_attribute_name = item_data["default_attribute_name"]
        except Exception:
            pass

    if "min_value" in item_data and hasattr(interface_item, "min_value"):
        try:
            interface_item.min_value = item_data["min_value"]
        except Exception:
            pass

    if "max_value" in item_data and hasattr(interface_item, "max_value"):
        try:
            interface_item.max_value = item_data["max_value"]
        except Exception:
            pass

    if "default_value" in item_data:
        _set_socket_like_default_value(interface_item, item_data["default_value"])


def _clear_tree_interface(tree):
    # 清空 node tree interface 項目
    interface = getattr(tree, "interface", None)
    if interface is None or not hasattr(interface, "items_tree"):
        return

    for item in list(interface.items_tree):
        try:
            interface.remove(item)
        except Exception:
            pass


def _build_tree_interface(tree, interface_data, strict_mode=False, warnings=None, clear_existing=True):
    # 依 JSON 建立 group tree interface，讓 Group Node 有正確輸入輸出
    normalized_items = _normalize_interface_data(interface_data)
    if not normalized_items:
        return

    interface = getattr(tree, "interface", None)
    if interface is None or not hasattr(interface, "new_socket"):
        _raise_or_warn(strict_mode, warnings, f"目前 Blender 無法為 node tree 建立 interface: {tree.name}")
        return

    if clear_existing:
        _clear_tree_interface(tree)

    for item_data in normalized_items:
        try:
            interface_item = interface.new_socket(
                name=item_data["name"],
                in_out=item_data["in_out"],
                socket_type=item_data["socket_type"],
            )
        except Exception as exc:
            _raise_or_warn(strict_mode, warnings, f"建立 interface socket 失敗: {item_data.get('name')}: {exc}")
            continue

        if "identifier" in item_data and hasattr(interface_item, "identifier"):
            try:
                interface_item.identifier = item_data["identifier"]
            except Exception:
                pass

        _apply_interface_item_settings(interface_item, item_data)


def _record_warning(warnings, message):
    # 收集非致命警告
    if warnings is not None:
        warnings.append(message)


def _raise_or_warn(strict_mode, warnings, message):
    # strict_mode 時拋錯，否則只記錄警告
    if strict_mode:
        raise ValueError(message)

    _record_warning(warnings, message)


def _find_group_tree_by_name(group_name):
    # 依名稱尋找既有 GeometryNodeTree
    if not group_name:
        return None

    tree = bpy.data.node_groups.get(group_name)
    if tree is None:
        return None

    if getattr(tree, "bl_idname", "") != "GeometryNodeTree":
        return None

    return tree


def _resolve_group_tree_reference(base_filepath, node_data, strict_mode, warnings, import_state=None):
    # 解析 group node 要使用的 GeometryNodeTree
    group_name = node_data.get("group_name")
    group_data = node_data.get("group_data")
    group_file = node_data.get("group_file")
    reference_key = _get_group_reference_key(base_filepath, node_data)

    if import_state is not None and reference_key is not None:
        cached_tree = import_state.group_cache.get(reference_key)
        if cached_tree is not None and cached_tree.name in bpy.data.node_groups:
            return cached_tree

    if isinstance(group_data, dict):
        resolved_group_name = group_name or group_data.get("group_name") or group_data.get("tree_name") or node_data.get("name") or "Imported Group"
        unique_group_name = _make_unique_group_name(resolved_group_name, import_state)
        group_tree = bpy.data.node_groups.new(unique_group_name, "GeometryNodeTree")

        try:
            _push_group_reference(import_state, reference_key)
            normalized_group_data = _normalize_build_json_data(group_data, group_name=resolved_group_name)
            if import_state is not None and reference_key is not None:
                import_state.group_cache[reference_key] = group_tree

            _import_tree_from_build_json(
                group_tree,
                normalized_group_data,
                clear_existing=True,
                base_filepath=base_filepath,
                import_state=import_state,
            )
        except Exception as exc:
            _pop_group_reference(import_state, reference_key)
            if import_state is not None and reference_key is not None:
                import_state.group_cache.pop(reference_key, None)
            bpy.data.node_groups.remove(group_tree)
            _raise_or_warn(strict_mode, warnings, f"Group data 匯入失敗: {resolved_group_name}: {exc}")
            return None
        finally:
            _pop_group_reference(import_state, reference_key)

        return group_tree

    if group_file:
        resolved_group_path = _resolve_json_path(base_filepath, group_file)
        if not resolved_group_path or not os.path.isfile(resolved_group_path):
            _raise_or_warn(strict_mode, warnings, f"找不到 group_file: {group_file}")
            return None

        try:
            group_data = _load_json_file(resolved_group_path)
        except Exception as exc:
            _raise_or_warn(strict_mode, warnings, f"讀取 group_file 失敗: {group_file}: {exc}")
            return None

        resolved_group_name = group_name or group_data.get("group_name") or group_data.get("tree_name") or os.path.splitext(os.path.basename(resolved_group_path))[0]
        unique_group_name = _make_unique_group_name(resolved_group_name, import_state)
        group_tree = bpy.data.node_groups.new(unique_group_name, "GeometryNodeTree")

        try:
            _push_group_reference(import_state, reference_key)
            normalized_group_data = _normalize_build_json_data(group_data, group_name=resolved_group_name)
            if import_state is not None and reference_key is not None:
                import_state.group_cache[reference_key] = group_tree

            _import_tree_from_build_json(
                group_tree,
                normalized_group_data,
                clear_existing=True,
                base_filepath=resolved_group_path,
                import_state=import_state,
            )
        except Exception as exc:
            _pop_group_reference(import_state, reference_key)
            if import_state is not None and reference_key is not None:
                import_state.group_cache.pop(reference_key, None)
            bpy.data.node_groups.remove(group_tree)
            _raise_or_warn(strict_mode, warnings, f"group_file 匯入失敗: {group_file}: {exc}")
            return None
        finally:
            _pop_group_reference(import_state, reference_key)

        return group_tree

    existing_tree = _find_group_tree_by_name(group_name)
    if existing_tree is not None:
        if import_state is not None and reference_key is not None:
            import_state.group_cache[reference_key] = existing_tree
        return existing_tree

    if group_name:
        _raise_or_warn(strict_mode, warnings, f"找不到 group_name 對應的 GeometryNodeTree: {group_name}")

    return None


def _apply_node_inputs(node, inputs_data, strict_mode=False, warnings=None):
    # 套用節點輸入 socket 的預設值
    if not isinstance(inputs_data, (dict, list, tuple)):
        return

    if isinstance(inputs_data, dict):
        input_items = []
        for socket_name, value in inputs_data.items():
            if isinstance(value, dict) and any(key in value for key in ("value", "default_value", "identifier", "index", "name")):
                socket_reference = {
                    "name": value.get("name", socket_name),
                    "identifier": value.get("identifier"),
                    "index": value.get("index"),
                }
                input_items.append((socket_reference, value.get("value", value.get("default_value"))))
            else:
                input_items.append(({"name": socket_name}, value))
    else:
        input_items = []
        for item in inputs_data:
            if not isinstance(item, dict):
                continue

            socket_reference = {
                "name": item.get("name"),
                "identifier": item.get("identifier"),
                "index": item.get("index"),
            }
            input_items.append((socket_reference, item.get("value", item.get("default_value"))))

    for socket_reference, value in input_items:
        socket = _find_socket(node.inputs, socket_reference)
        if socket is None or not hasattr(socket, "default_value"):
            _raise_or_warn(strict_mode, warnings, f"找不到輸入 socket: {socket_reference}")
            continue

        try:
            socket.default_value = value
        except Exception:
            try:
                if isinstance(socket.default_value, bpy.types.bpy_prop_array):
                    for index, item in enumerate(value):
                        socket.default_value[index] = item
            except Exception:
                _raise_or_warn(strict_mode, warnings, f"無法設定輸入 socket 預設值: {socket.name}")


def _apply_custom_properties(node, custom_properties):
    # 套用 Blender ID Property 自訂欄位
    if not isinstance(custom_properties, dict):
        return

    for property_name, value in custom_properties.items():
        try:
            node[property_name] = value
        except Exception:
            pass


def _apply_node_properties(node, properties_data):
    # 套用節點本身的額外屬性，例如 operation、data_type 等
    if not isinstance(properties_data, dict):
        return

    for property_name, value in properties_data.items():
        if not hasattr(node, property_name):
            continue

        try:
            setattr(node, property_name, value)
        except Exception:
            pass


def _create_node_from_build_data(tree, node_data, strict_mode=False, warnings=None, base_filepath=None, place_offset=(0.0, 0.0), import_state=None):
    # 根據 build JSON 建立單一節點
    bl_idname = node_data.get("bl_idname")
    if not bl_idname:
        raise ValueError("節點缺少 bl_idname")

    node = tree.nodes.new(bl_idname)

    warnings_optional = node_data.get("warnings_optional")
    if isinstance(warnings_optional, list):
        for warning_message in warnings_optional:
            _record_warning(warnings, f"節點 {node_data.get('name') or bl_idname}: {warning_message}")

    if "name" in node_data:
        try:
            node.name = node_data["name"]
        except Exception:
            pass

    if "label" in node_data:
        try:
            node.label = node_data["label"]
        except Exception:
            pass

    if "location" in node_data and isinstance(node_data["location"], (list, tuple)) and len(node_data["location"]) >= 2:
        try:
            offset_x, offset_y = _coerce_vector2(place_offset)
            node.location = (
                float(node_data["location"][0]) + offset_x,
                float(node_data["location"][1]) + offset_y,
            )
        except Exception:
            pass
    else:
        offset_x, offset_y = _coerce_vector2(place_offset)
        if offset_x != 0.0 or offset_y != 0.0:
            try:
                node.location = (float(node.location.x) + offset_x, float(node.location.y) + offset_y)
            except Exception:
                pass

    if "width" in node_data:
        try:
            node.width = float(node_data["width"])
        except Exception:
            pass

    if "mute" in node_data:
        try:
            node.mute = bool(node_data["mute"])
        except Exception:
            pass

    if "hide" in node_data:
        try:
            node.hide = bool(node_data["hide"])
        except Exception:
            pass

    group_tree = _resolve_group_tree_reference(base_filepath, node_data, strict_mode, warnings, import_state=import_state)
    if group_tree is not None and hasattr(node, "node_tree"):
        try:
            node.node_tree = group_tree
        except Exception as exc:
            _raise_or_warn(strict_mode, warnings, f"無法將 group 指定到節點 {node.name}: {exc}")

    _apply_node_properties(node, node_data.get("properties"))
    _apply_node_inputs(node, node_data.get("inputs"), strict_mode=strict_mode, warnings=warnings)
    _apply_custom_properties(node, node_data.get("custom_properties"))

    return node


def _get_link_socket_reference(link_data, key_prefix):
    # 從 link data 取得 socket 參照，支援新舊格式
    direct_reference = link_data.get(f"{key_prefix}_socket")
    if isinstance(direct_reference, dict):
        return direct_reference

    reference = {
        "name": link_data.get(f"{key_prefix}_socket_name"),
        "identifier": link_data.get(f"{key_prefix}_socket_identifier"),
        "index": link_data.get(f"{key_prefix}_socket_index"),
    }

    if any(value is not None and value != "" for value in reference.values()):
        return reference

    return _normalize_socket_reference(direct_reference)


def _import_tree_from_build_json(tree, data, clear_existing, base_filepath=None, import_state=None):
    # 從 AI build JSON 建立 Geometry Nodes 節點圖
    data = _normalize_build_json_data(data)

    if import_state is None:
        import_state = _create_build_import_state()

    root_reference_key = None
    pushed_root_reference = False
    if base_filepath:
        root_reference_key = ("group_file", os.path.normcase(os.path.normpath(base_filepath)))
        if root_reference_key not in import_state.import_stack:
            _push_group_reference(import_state, root_reference_key)
            pushed_root_reference = True

    try:
        if data.get("format") != "geometry_nodes_ai_build":
            raise ValueError("JSON format 必須是 geometry_nodes_ai_build")

        format_version = int(data.get("format_version", 1))
        if format_version > SUPPORTED_BUILD_FORMAT_VERSION:
            raise ValueError(
                f"不支援的 build JSON format_version: {format_version}，目前最高支援 {SUPPORTED_BUILD_FORMAT_VERSION}"
            )

        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            target_blender_version = metadata.get("target_blender_version")
            if isinstance(target_blender_version, (list, tuple)) and len(target_blender_version) >= 2:
                current_version = tuple(bpy.app.version)
                target_version = tuple(int(item) for item in target_blender_version[:3])
                if current_version < target_version:
                    raise ValueError(f"此 JSON 目標 Blender 版本為 {target_version}，目前版本為 {current_version}")

        strict_mode = _as_bool(data.get("strict_mode", False))
        append_mode = _as_bool(data.get("append_mode", False))
        place_offset = _coerce_vector2(data.get("place_offset"), default=(0.0, 0.0))

        warnings = []

        if append_mode:
            clear_existing = False

        if clear_existing:
            _clear_tree(tree)

        _build_tree_interface(
            tree,
            data.get("interface"),
            strict_mode=strict_mode,
            warnings=warnings,
            clear_existing=clear_existing,
        )

        nodes_data = data.get("nodes", [])
        links_data = data.get("links", [])
        node_map = {}

        for index, node_data in enumerate(nodes_data):
            try:
                node = _create_node_from_build_data(
                    tree,
                    node_data,
                    strict_mode=strict_mode,
                    warnings=warnings,
                    base_filepath=base_filepath,
                    place_offset=place_offset,
                    import_state=import_state,
                )
            except Exception as exc:
                _raise_or_warn(strict_mode, warnings, f"建立節點失敗 index={index}: {exc}")
                continue

            node_id = node_data.get("id") or node_data.get("name") or f"node_{index}"
            node_map[node_id] = node

        for link_data in links_data:
            from_node = node_map.get(link_data.get("from_node"))
            to_node = node_map.get(link_data.get("to_node"))

            if from_node is None or to_node is None:
                _raise_or_warn(strict_mode, warnings, f"連線節點不存在: {link_data}")
                continue

            from_socket = _find_socket(from_node.outputs, _get_link_socket_reference(link_data, "from"))
            to_socket = _find_socket(to_node.inputs, _get_link_socket_reference(link_data, "to"))

            if from_socket is None or to_socket is None:
                _raise_or_warn(strict_mode, warnings, f"連線 socket 不存在: {link_data}")
                continue

            try:
                tree.links.new(from_socket, to_socket)
            except Exception as exc:
                _raise_or_warn(strict_mode, warnings, f"建立連線失敗: {link_data}: {exc}")

        return warnings
    finally:
        if pushed_root_reference:
            _pop_group_reference(import_state, root_reference_key)


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

    import_json_path: bpy.props.StringProperty(
        name="導入 JSON",
        subtype="FILE_PATH",
        default="",
    )

    clear_before_import: bpy.props.BoolProperty(
        name="導入前清空節點",
        description="導入前先清空目標節點樹中的既有節點",
        default=False,
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


class GNEXPORTER_OT_Import(bpy.types.Operator):
    # 讀取 AI build JSON 並建立 Geometry Nodes
    bl_idname = "gn_exporter.import_json"
    bl_label = "由 JSON 生成 GN"
    bl_description = "Import AI build JSON and create Geometry Nodes"

    def execute(self, context):
        props = context.scene.gn_exporter_props
        import_path = bpy.path.abspath(props.import_json_path).strip()

        if not import_path:
            self.report({"ERROR"}, "請先指定導入 JSON 檔案")
            return {"CANCELLED"}

        if not os.path.isfile(import_path):
            self.report({"ERROR"}, "找不到指定的 JSON 檔案")
            return {"CANCELLED"}

        editor_tree = _get_geometry_node_editor_tree(context)
        tree = None

        if editor_tree is not None:
            tree = editor_tree
        else:
            _, _, tree = _get_modifier_node_tree(context, props.modifier_name)

        if tree is None:
            self.report({"ERROR"}, "找不到可導入的 Geometry Nodes Tree")
            return {"CANCELLED"}

        try:
            data = _load_json_file(import_path)
        except Exception as exc:
            self.report({"ERROR"}, f"讀取 JSON 失敗: {exc}")
            return {"CANCELLED"}

        try:
            clear_existing = _as_bool(data.get("clear_existing_nodes", props.clear_before_import))
            warnings = _import_tree_from_build_json(
                tree,
                data,
                clear_existing,
                base_filepath=import_path,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"導入 JSON 失敗: {exc}")
            return {"CANCELLED"}

        if warnings:
            self.report({"WARNING"}, f"已生成 Geometry Nodes，但有 {len(warnings)} 個警告；詳見 Console")
            for warning_message in warnings:
                print(f"[GN Exporter][Import Warning] {warning_message}")
        else:
            self.report({"INFO"}, "已根據 JSON 生成 Geometry Nodes")

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

        layout.separator()
        layout.prop(props, "import_json_path")
        layout.prop(props, "clear_before_import")
        layout.operator("gn_exporter.import_json", icon="IMPORT")


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

            layout.separator()
            layout.prop(props, "import_json_path")
            layout.prop(props, "clear_before_import")
            layout.operator("gn_exporter.import_json", icon="IMPORT")
        else:
            # 若沒有可用 Modifier，顯示提示訊息
            layout.label(text="目前作用中物件沒有可導出的 GN Modifier", icon="INFO")


# Blender 要註冊的類別清單
classes = (
    GNEXPORTER_Props,
    GNEXPORTER_OT_Export,
    GNEXPORTER_OT_Import,
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