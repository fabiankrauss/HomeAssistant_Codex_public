/*
 * Lovelace Pop-up Grid Editor - TypeScript logic
 * Provides YAML parsing, transformation, and serialization utilities for the UI.
 */
function stripComments(line) {
    let inSingle = false;
    let inDouble = false;
    for (let i = 0; i < line.length; i += 1) {
        const ch = line[i];
        if (ch === "'" && !inDouble) {
            inSingle = !inSingle;
        }
        else if (ch === "\"" && !inSingle) {
            let backslashCount = 0;
            let j = i - 1;
            while (j >= 0 && line[j] === "\\") {
                backslashCount += 1;
                j -= 1;
            }
            if (backslashCount % 2 === 0) {
                inDouble = !inDouble;
            }
        }
        else if (ch === "#" && !inSingle && !inDouble) {
            return line.slice(0, i);
        }
    }
    return line;
}
function isWhitespaceOnly(value) {
    return /^\s*$/.test(value);
}
function parseQuotedString(raw) {
    if (raw.startsWith("\"") && raw.endsWith("\"")) {
        return raw
            .slice(1, -1)
            .replace(/\\n/g, "\n")
            .replace(/\\"/g, '"')
            .replace(/\\\\/g, "\\");
    }
    if (raw.startsWith("'") && raw.endsWith("'")) {
        return raw.slice(1, -1).replace(/''/g, "'");
    }
    return raw;
}
function parseScalar(rawValue) {
    const trimmed = rawValue.trim();
    if (trimmed === "" || trimmed === "null" || trimmed === "~") {
        return null;
    }
    if (trimmed === "true" || trimmed === "True") {
        return true;
    }
    if (trimmed === "false" || trimmed === "False") {
        return false;
    }
    if (/^[-+]?[0-9]+$/.test(trimmed)) {
        return Number.parseInt(trimmed, 10);
    }
    if (/^[-+]?[0-9]*\.[0-9]+$/.test(trimmed)) {
        return Number.parseFloat(trimmed);
    }
    if ((trimmed.startsWith("\"") && trimmed.endsWith("\"")) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
        return parseQuotedString(trimmed);
    }
    if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
        return parseInlineArray(trimmed.slice(1, -1));
    }
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
        return parseInlineObject(trimmed.slice(1, -1));
    }
    return trimmed;
}
function splitTopLevel(text, separator) {
    const result = [];
    let depth = 0;
    let start = 0;
    let inSingle = false;
    let inDouble = false;
    for (let i = 0; i < text.length; i += 1) {
        const ch = text[i];
        if (ch === "'" && !inDouble) {
            inSingle = !inSingle;
            continue;
        }
        if (ch === "\"" && !inSingle) {
            let backslashes = 0;
            let j = i - 1;
            while (j >= 0 && text[j] === "\\") {
                backslashes += 1;
                j -= 1;
            }
            if (backslashes % 2 === 0) {
                inDouble = !inDouble;
            }
            continue;
        }
        if (inSingle || inDouble) {
            continue;
        }
        if (ch === "{" || ch === "[") {
            depth += 1;
        }
        else if (ch === "}" || ch === "]") {
            depth = Math.max(0, depth - 1);
        }
        else if (ch === separator && depth === 0) {
            result.push(text.slice(start, i).trim());
            start = i + 1;
        }
    }
    const finalPart = text.slice(start).trim();
    if (finalPart !== "") {
        result.push(finalPart);
    }
    return result;
}
function parseInlineArray(body) {
    if (isWhitespaceOnly(body)) {
        return [];
    }
    const parts = splitTopLevel(body, ",");
    return parts.map((part) => parseScalar(part));
}
function parseInlineObject(body) {
    const obj = {};
    if (isWhitespaceOnly(body)) {
        return obj;
    }
    const parts = splitTopLevel(body, ",");
    for (const part of parts) {
        const colonIdx = part.indexOf(":");
        if (colonIdx === -1) {
            throw new Error(`Invalid inline object fragment: ${part}`);
        }
        const key = part.slice(0, colonIdx).trim();
        const rawValue = part.slice(colonIdx + 1).trim();
        obj[key] = parseScalar(rawValue);
    }
    return obj;
}
export function parseYAML(text) {
    const lines = text
        .replace(/\r\n?/g, "\n")
        .split("\n")
        .map((line) => stripComments(line))
        .map((line) => line.replace(/\t/g, "  "));
    const filteredLines = lines.map((line) => line.replace(/\s+$/, ""));
    const stack = [
        { type: "object", container: {}, indent: -1, pending: null },
    ];
    for (let index = 0; index < filteredLines.length; index += 1) {
        const rawLine = filteredLines[index];
        if (isWhitespaceOnly(rawLine)) {
            continue;
        }
        const indentMatch = rawLine.match(/^(\s*)/u);
        const indent = indentMatch ? indentMatch[0].length : 0;
        const trimmed = rawLine.trim();
        while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
            stack.pop();
        }
        let frame = stack[stack.length - 1];
        // Resolve pending keys if necessary
        if (frame.pending && indent > frame.pending.indent) {
            if (trimmed.startsWith("-")) {
                const arr = [];
                frame.container[frame.pending.key] = arr;
                const arrayFrame = {
                    type: "array",
                    container: arr,
                    indent: frame.pending.indent,
                    pending: null,
                };
                stack.push(arrayFrame);
                frame.pending = null;
                frame = arrayFrame;
            }
            else {
                const obj = {};
                frame.container[frame.pending.key] = obj;
                const objectFrame = {
                    type: "object",
                    container: obj,
                    indent: frame.pending.indent,
                    pending: null,
                };
                stack.push(objectFrame);
                frame.pending = null;
                frame = objectFrame;
            }
        }
        else if (frame.pending && indent <= frame.pending.indent) {
            frame.pending = null;
        }
        frame = stack[stack.length - 1];
        if (trimmed.startsWith("-")) {
            if (frame.type === "object") {
                if (!frame.pending) {
                    throw new Error(`Unexpected list item at line ${index + 1}`);
                }
                const arr = [];
                frame.container[frame.pending.key] = arr;
                const arrayFrame = {
                    type: "array",
                    container: arr,
                    indent: frame.pending.indent,
                    pending: null,
                };
                stack.push(arrayFrame);
                frame.pending = null;
                frame = arrayFrame;
            }
            if (frame.type !== "array") {
                throw new Error(`List item without array context at line ${index + 1}`);
            }
            const content = trimmed.slice(1).trim();
            if (content === "") {
                const obj = {};
                frame.container.push(obj);
                stack.push({ type: "object", container: obj, indent, pending: null });
                continue;
            }
            if (content.includes(":")) {
                const colonIndex = content.indexOf(":");
                const key = content.slice(0, colonIndex).trim();
                const valuePart = content.slice(colonIndex + 1).trim();
                const obj = {};
                if (valuePart === "") {
                    obj[key] = {};
                    frame.container.push(obj);
                    stack.push({
                        type: "object",
                        container: obj,
                        indent,
                        pending: { key, indent },
                    });
                }
                else {
                    obj[key] = parseScalar(valuePart);
                    frame.container.push(obj);
                    stack.push({ type: "object", container: obj, indent, pending: null });
                }
            }
            else {
                frame.container.push(parseScalar(content));
            }
            continue;
        }
        const colonIndex = trimmed.indexOf(":");
        if (colonIndex === -1) {
            throw new Error(`Unable to parse line ${index + 1}: ${trimmed}`);
        }
        const key = trimmed.slice(0, colonIndex).trim();
        const valuePart = trimmed.slice(colonIndex + 1).trim();
        if (valuePart === "") {
            frame.pending = { key, indent };
        }
        else {
            frame.container[key] = parseScalar(valuePart);
        }
    }
    while (stack.length > 1) {
        const top = stack.pop();
        if (top && top.pending) {
            stack[stack.length - 1].container[top.pending.key] = {};
        }
    }
    return stack[0].container;
}
function needsQuoting(value) {
    return !/^[-A-Za-z0-9_\.]+$/.test(value) || value.includes(": ") || value === "";
}
function quoteString(value) {
    return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}
function serializeScalar(value) {
    if (value === null || value === undefined) {
        return "null";
    }
    if (typeof value === "boolean") {
        return value ? "true" : "false";
    }
    if (typeof value === "number") {
        return Number.isFinite(value) ? String(value) : "null";
    }
    if (typeof value === "string") {
        return needsQuoting(value) ? quoteString(value) : value;
    }
    return quoteString(String(value));
}
export function stringifyYAML(value, indentSize = 2, indentLevel = 0) {
    const indent = " ".repeat(indentLevel);
    if (Array.isArray(value)) {
        if (value.length === 0) {
            return `${indent}[]`;
        }
        const childIndent = " ".repeat(indentLevel + indentSize);
        return value
            .map((item) => {
            if (typeof item === "object" && item !== null) {
                const nested = stringifyYAML(item, indentSize, indentLevel + indentSize);
                const [firstLine, ...rest] = nested.split("\n");
                if (rest.length === 0) {
                    return `${indent}- ${firstLine.trimStart()}`;
                }
                const tail = rest
                    .map((line) => {
                    const relative = line.startsWith(childIndent)
                        ? line.slice(childIndent.length)
                        : line.trimStart();
                    return `${childIndent}${relative}`;
                })
                    .join("\n");
                return `${indent}- ${firstLine.trimStart()}\n${tail}`;
            }
            return `${indent}- ${serializeScalar(item)}`;
        })
            .join("\n");
    }
    if (typeof value === "object" && value !== null) {
        const entries = Object.entries(value);
        if (entries.length === 0) {
            return `${indent}{}`;
        }
        return entries
            .map(([key, val]) => {
            const prefix = `${indent}${needsQuoting(key) ? quoteString(key) : key}:`;
            if (typeof val === "object" && val !== null) {
                const nested = stringifyYAML(val, indentSize, indentLevel + indentSize);
                return `${prefix}\n${nested}`;
            }
            return `${prefix} ${serializeScalar(val)}`;
        })
            .join("\n");
    }
    return `${indent}${serializeScalar(value)}`;
}
export function slugifyArea(name) {
    const translit = {
        ä: "ae",
        ö: "oe",
        ü: "ue",
        ß: "ss",
    };
    const lower = name.trim().toLowerCase();
    let result = "";
    for (const char of lower) {
        if (translit[char]) {
            result += translit[char];
        }
        else if (/[a-z0-9]/.test(char)) {
            result += char;
        }
        else if (char === " " || char === "/") {
            result += "_";
        }
    }
    return result;
}
function normaliseRoom(value) {
    return value.trim().toLowerCase();
}
function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isBubblePopup(stack) {
    if (!isRecord(stack)) {
        return false;
    }
    if (stack.type !== "vertical-stack") {
        return false;
    }
    const cards = stack.cards;
    if (!Array.isArray(cards) || cards.length === 0) {
        return false;
    }
    const first = cards[0];
    if (!isRecord(first)) {
        return false;
    }
    return first.type === "custom:bubble-card" && first.card_type === "pop-up";
}
function extractAreaFromNode(node) {
    if (isRecord(node)) {
        if (typeof node.area === "string") {
            return node.area;
        }
        if (isRecord(node.target) && typeof node.target.area_id === "string") {
            return node.target.area_id;
        }
        for (const value of Object.values(node)) {
            const extracted = extractAreaFromNode(value);
            if (extracted) {
                return extracted;
            }
        }
    }
    else if (Array.isArray(node)) {
        for (const item of node) {
            const extracted = extractAreaFromNode(item);
            if (extracted) {
                return extracted;
            }
        }
    }
    return null;
}
export function findExistingStack(grid, room, areaId, strategy) {
    const cards = grid.cards;
    if (!Array.isArray(cards)) {
        throw new Error("Grid cards structure is invalid or missing");
    }
    const desiredName = normaliseRoom(room);
    const desiredHash = `#${areaId}-popup`;
    let foundIndex = null;
    const duplicates = [];
    cards.forEach((stack, index) => {
        if (!isBubblePopup(stack)) {
            return;
        }
        const first = stack.cards;
        const head = first[0];
        let match = false;
        if (strategy === "name") {
            const name = typeof head.name === "string" ? normaliseRoom(head.name) : "";
            match = name === desiredName;
        }
        else if (strategy === "hash") {
            match = head.hash === desiredHash;
        }
        else if (strategy === "area") {
            const extracted = extractAreaFromNode(stack);
            match = extracted === areaId;
        }
        else {
            throw new Error(`Unknown detection strategy: ${strategy}`);
        }
        if (match) {
            if (foundIndex === null) {
                foundIndex = index;
            }
            else {
                duplicates.push(index);
            }
        }
    });
    return { index: foundIndex, duplicates };
}
function deepClone(value) {
    if (typeof structuredClone === "function") {
        return structuredClone(value);
    }
    return JSON.parse(JSON.stringify(value));
}
function traverse(node, visitor, parent = null, key = null) {
    visitor(node, parent, key);
    if (Array.isArray(node)) {
        node.forEach((item, index) => traverse(item, visitor, node, index));
    }
    else if (isRecord(node)) {
        Object.entries(node).forEach(([childKey, childValue]) => {
            traverse(childValue, visitor, node, childKey);
        });
    }
}
function replacePlaceholders(node, replacements, iconValue) {
    let replaced = false;
    let iconApplied = false;
    traverse(node, (value, parent, key) => {
        if (typeof value === "string") {
            if (replacements[value]) {
                if (parent && key !== null) {
                    if (Array.isArray(parent)) {
                        parent[key] = replacements[value];
                    }
                    else if (isRecord(parent)) {
                        parent[key] = replacements[value];
                    }
                    replaced = true;
                }
            }
            else if (value === "__ICON__" && iconValue && parent && key !== null) {
                if (Array.isArray(parent)) {
                    parent[key] = iconValue;
                }
                else if (isRecord(parent)) {
                    parent[key] = iconValue;
                }
                iconApplied = true;
            }
        }
    });
    return { replaced, iconApplied };
}
function applyHeuristics(stack, room, areaId) {
    traverse(stack, (value, parent, key) => {
        if (!parent || key === null) {
            return;
        }
        if (isRecord(parent)) {
            if (key === "area") {
                parent[key] = areaId;
            }
            if (key === "target" && isRecord(value)) {
                value.area_id = areaId;
            }
        }
    });
    if (Array.isArray(stack.cards) && stack.cards.length > 0) {
        const first = stack.cards[0];
        if (isRecord(first)) {
            if ("name" in first) {
                first.name = room;
            }
            if ("hash" in first) {
                first.hash = `#${areaId}-popup`;
            }
        }
    }
}
export function deepApplyTemplate(template, room, areaId, iconMap) {
    const stack = deepClone(template);
    const replacements = {
        "__AREA_NAME__": room,
        "__AREA_ID__": areaId,
        "__HASH__": `#${areaId}-popup`,
    };
    const iconValue = iconMap ? iconMap[room] ?? null : null;
    const { replaced: placeholdersUsed, iconApplied } = replacePlaceholders(stack, replacements, iconValue);
    applyHeuristics(stack, room, areaId);
    return { stack, replacedPlaceholders: placeholdersUsed, iconApplied };
}
export function replaceOrAppend(grid, index, stack, insertMode) {
    if (!Array.isArray(grid.cards)) {
        throw new Error("Grid cards must be an array");
    }
    if (index !== null && insertMode === "keep-index") {
        grid.cards[index] = stack;
        return index;
    }
    if (index !== null) {
        grid.cards[index] = stack;
        return index;
    }
    grid.cards.push(stack);
    return grid.cards.length - 1;
}
export function processGrid(gridSource, roomsSource, templateSource, options) {
    const grid = parseYAML(gridSource);
    const template = parseYAML(templateSource);
    let rooms;
    try {
        rooms = JSON.parse(roomsSource);
    }
    catch (error) {
        throw new Error("Rooms JSON could not be parsed");
    }
    if (!Array.isArray(rooms)) {
        throw new Error("Rooms JSON must be a list of strings");
    }
    if (!isRecord(grid) || grid.type !== "grid" || !Array.isArray(grid.cards)) {
        throw new Error("Grid YAML must describe a Lovelace grid with cards");
    }
    if (!isRecord(template) || template.type !== "vertical-stack") {
        throw new Error("Template YAML must be a vertical-stack");
    }
    if (!Array.isArray(template.cards) || template.cards.length === 0) {
        throw new Error("Template stack requires cards");
    }
    const firstCard = template.cards[0];
    if (!isRecord(firstCard) || firstCard.type !== "custom:bubble-card" || firstCard.card_type !== "pop-up") {
        throw new Error("Template first card must be a custom:bubble-card pop-up");
    }
    const gridCopy = deepClone(grid);
    const templateCopy = deepClone(template);
    const report = [];
    rooms.forEach((roomName) => {
        if (typeof roomName !== "string") {
            throw new Error("Rooms JSON must only contain strings");
        }
        const areaId = slugifyArea(roomName);
        const match = findExistingStack(gridCopy, roomName, areaId, options.detectBy);
        const applied = deepApplyTemplate(templateCopy, roomName, areaId, options.iconMap);
        const index = replaceOrAppend(gridCopy, match.index, applied.stack, options.insertMode);
        report.push({
            room: roomName,
            areaId,
            action: match.index === null ? "created" : "updated",
            index,
            duplicates: match.duplicates,
            placeholdersUsed: applied.replacedPlaceholders,
        });
    });
    const yaml = stringifyYAML(gridCopy, options.indent);
    return { yaml, report };
}
