(function () {
    "use strict";

    var roots = document.querySelectorAll(
        '.rbtx-flagship-stage[data-rbtx-system-view="interactive-bom-pyramid"]'
    );

    roots.forEach(initFlagship);

    function initFlagship(root) {
        var canvas = root.querySelector("[data-rbtx-canvas]");
        var systemScript = root.querySelector("[data-rbtx-system-data]");
        var systems = readSystems(systemScript);

        initSystemDetails(root, systems);
        initMissionBrief(root);

        if (!canvas || !canvas.getContext) {
            return;
        }

        var context = canvas.getContext("2d");
        if (!context) {
            return;
        }

        var viewer =
            canvas.closest(".rbtx-viewer-shell") || canvas.parentElement;
        var resetButton = root.querySelector('[data-rbtx-view-action="reset"]');
        var explodeButton = root.querySelector('[data-rbtx-view-action="explode"]');
        var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
        var canonicalGroups = [
            "perception",
            "compute",
            "energy",
            "safety",
            "mobility",
            "manipulation",
            "tooling",
            "structure"
        ];
        var systemGroups = new Map();
        var state = {
            width: 1,
            height: 1,
            pixelRatio: 1,
            yaw: -0.32,
            pitch: -0.08,
            zoom: 1,
            explode: 0,
            explodeTarget: 0,
            activeGroup: canonicalGroups[0],
            dragging: false,
            pointerId: null,
            previousX: 0,
            previousY: 0,
            visible: true,
            interactedAt: performance.now(),
            frame: 0
        };

        systems.forEach(function (system, index) {
            systemGroups.set(
                system.id,
                system.group || canonicalGroups[index] || canonicalGroups[0]
            );
        });

        var shapes = robotShapes();
        var fallbackAnchors = {
            perception: [0, 1.65, 0.1],
            compute: [0.05, 0.52, 0.1],
            energy: [-0.1, -1.42, 0.2],
            safety: [1.45, -1.62, 0.72],
            mobility: [1.25, -2.25, 0.68],
            manipulation: [-1.56, -0.22, 0.25],
            tooling: [-1.76, -1.5, 0.18],
            structure: [0.75, -0.25, 0.72]
        };

        function resize() {
            var bounds = canvas.getBoundingClientRect();
            var ratio = Math.min(window.devicePixelRatio || 1, 2);
            var width = Math.max(1, Math.round(bounds.width));
            var height = Math.max(1, Math.round(bounds.height));

            if (
                state.width === width &&
                state.height === height &&
                state.pixelRatio === ratio
            ) {
                return;
            }

            state.width = width;
            state.height = height;
            state.pixelRatio = ratio;
            canvas.width = Math.round(width * ratio);
            canvas.height = Math.round(height * ratio);
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
        }

        function render(now) {
            state.frame = window.requestAnimationFrame(render);
            if (!state.visible) {
                return;
            }

            resize();

            if (
                !reducedMotion.matches &&
                !state.dragging &&
                now - state.interactedAt > 5500
            ) {
                state.yaw += 0.00055 * Math.min(32, now - (render.lastNow || now));
            }
            render.lastNow = now;

            state.explode += (state.explodeTarget - state.explode) * 0.09;
            drawScene(context, state, shapes);
            positionHotspots(root, viewer, systems, systemGroups, fallbackAnchors, state);
            root.classList.add("rbtx-viewer-ready");
        }

        function markInteraction() {
            state.interactedAt = performance.now();
        }

        canvas.addEventListener("pointerdown", function (event) {
            state.dragging = true;
            state.pointerId = event.pointerId;
            state.previousX = event.clientX;
            state.previousY = event.clientY;
            canvas.setPointerCapture(event.pointerId);
            markInteraction();
        });

        canvas.addEventListener("pointermove", function (event) {
            if (!state.dragging || event.pointerId !== state.pointerId) {
                return;
            }
            var deltaX = event.clientX - state.previousX;
            var deltaY = event.clientY - state.previousY;
            state.previousX = event.clientX;
            state.previousY = event.clientY;
            state.yaw += deltaX * 0.008;
            state.pitch = clamp(state.pitch + deltaY * 0.004, -0.34, 0.22);
            markInteraction();
        });

        function endPointer(event) {
            if (event.pointerId !== state.pointerId) {
                return;
            }
            state.dragging = false;
            state.pointerId = null;
            markInteraction();
        }

        canvas.addEventListener("pointerup", endPointer);
        canvas.addEventListener("pointercancel", endPointer);

        canvas.addEventListener(
            "wheel",
            function (event) {
                event.preventDefault();
                state.zoom = clamp(state.zoom - event.deltaY * 0.0007, 0.72, 1.34);
                markInteraction();
            },
            {passive: false}
        );

        canvas.addEventListener("keydown", function (event) {
            var handled = true;
            if (event.key === "ArrowLeft") {
                state.yaw -= 0.12;
            } else if (event.key === "ArrowRight") {
                state.yaw += 0.12;
            } else if (event.key === "ArrowUp") {
                state.pitch = clamp(state.pitch - 0.08, -0.34, 0.22);
            } else if (event.key === "ArrowDown") {
                state.pitch = clamp(state.pitch + 0.08, -0.34, 0.22);
            } else if (event.key === "+" || event.key === "=") {
                state.zoom = clamp(state.zoom + 0.08, 0.72, 1.34);
            } else if (event.key === "-" || event.key === "_") {
                state.zoom = clamp(state.zoom - 0.08, 0.72, 1.34);
            } else if (event.key === "Home") {
                resetView();
            } else {
                handled = false;
            }

            if (handled) {
                event.preventDefault();
                markInteraction();
            }
        });

        function resetView() {
            state.yaw = -0.32;
            state.pitch = -0.08;
            state.zoom = 1;
            state.explodeTarget = 0;
            if (explodeButton) {
                explodeButton.setAttribute("aria-pressed", "false");
            }
            markInteraction();
        }

        if (resetButton) {
            resetButton.addEventListener("click", resetView);
        }

        if (explodeButton) {
            explodeButton.addEventListener("click", function () {
                var expanded = state.explodeTarget < 0.5;
                state.explodeTarget = expanded ? 1 : 0;
                explodeButton.setAttribute("aria-pressed", expanded ? "true" : "false");
                markInteraction();
            });
        }

        root.addEventListener("rbtx:systemchange", function (event) {
            var id = event.detail && event.detail.id;
            if (id && systemGroups.has(id)) {
                state.activeGroup = systemGroups.get(id);
                markInteraction();
            }
        });

        if ("IntersectionObserver" in window) {
            var observer = new IntersectionObserver(
                function (entries) {
                    state.visible = entries[0] ? entries[0].isIntersecting : true;
                },
                {rootMargin: "160px"}
            );
            observer.observe(viewer);
        }

        if ("ResizeObserver" in window) {
            new ResizeObserver(resize).observe(viewer);
        } else {
            window.addEventListener("resize", resize, {passive: true});
        }

        resize();
        state.frame = window.requestAnimationFrame(render);
    }

    function readSystems(script) {
        if (!script) {
            return [];
        }

        try {
            var payload = JSON.parse(script.textContent || "[]");
            var source = Array.isArray(payload) ? payload : payload.systems;
            if (!Array.isArray(source)) {
                return [];
            }

            return source.map(function (system, index) {
                return {
                    id: String(system.id || system.key || "system-" + (index + 1)),
                    group: system.group ? String(system.group) : "",
                    title: String(system.title || system.label || system.name || ""),
                    summary: String(system.summary || ""),
                    assemblies: Array.isArray(system.assemblies) ? system.assemblies : [],
                    components: Array.isArray(system.components) ? system.components : [],
                    anchor: Array.isArray(system.anchor) ? system.anchor : null
                };
            });
        } catch (error) {
            return [];
        }
    }

    function initSystemDetails(root, systems) {
        var buttons = root.querySelectorAll("[data-rbtx-system]");
        var title = root.querySelector("[data-rbtx-detail-title]");
        var summary = root.querySelector("[data-rbtx-detail-summary]");
        var assemblies = root.querySelector("[data-rbtx-detail-assemblies]");
        var components = root.querySelector("[data-rbtx-detail-components]");
        var systemMap = new Map();

        systems.forEach(function (system) {
            systemMap.set(system.id, system);
        });

        function selectSystem(id, focusDetail) {
            var system = systemMap.get(id);
            if (!system) {
                return;
            }

            buttons.forEach(function (button) {
                var isActive = button.getAttribute("data-rbtx-system") === id;
                button.classList.toggle("is-active", isActive);
                button.setAttribute("aria-pressed", isActive ? "true" : "false");
            });

            if (title) {
                title.textContent = system.title;
            }
            if (summary) {
                summary.textContent = system.summary;
            }
            replaceList(assemblies, system.assemblies);
            replaceList(components, system.components);

            root.dispatchEvent(
                new CustomEvent("rbtx:systemchange", {
                    bubbles: false,
                    detail: {id: id}
                })
            );

            if (focusDetail && title) {
                title.setAttribute("tabindex", "-1");
                title.focus({preventScroll: true});
            }
        }

        buttons.forEach(function (button) {
            button.addEventListener("click", function () {
                selectSystem(button.getAttribute("data-rbtx-system") || "", false);
            });
        });

        var initial =
            root.querySelector('[data-rbtx-system][aria-pressed="true"]') ||
            buttons[0];
        if (initial) {
            selectSystem(initial.getAttribute("data-rbtx-system") || "", false);
        }
    }

    function replaceList(element, values) {
        if (!element) {
            return;
        }
        element.replaceChildren();
        values.forEach(function (value) {
            var item = document.createElement("li");
            item.textContent = typeof value === "string"
                ? value
                : String(value.title || value.name || "");
            element.appendChild(item);
        });
    }

    function initMissionBrief(root) {
        var form = root.querySelector("#mission-profile");
        var buildButton = root.querySelector("[data-rbtx-build-brief]");
        var output = root.querySelector("[data-rbtx-brief-output]");
        var text = root.querySelector("[data-rbtx-brief-text]");
        var copyButton = root.querySelector("[data-rbtx-copy-brief]");

        if (!form || !text) {
            return;
        }

        function value(name) {
            var field = form.elements.namedItem(name);
            if (!field) {
                return "";
            }
            var option = field.options && field.options[field.selectedIndex];
            return option ? option.text.trim() : String(field.value || "").trim();
        }

        function buildBrief(event) {
            if (event) {
                event.preventDefault();
            }

            var lines = [
                "Mission: " + value("mission") + ".",
                "Work envelope: " + value("envelope") + ".",
                "Human interaction: " + value("interaction") + ".",
                "Operating setting: " + value("setting") + ".",
                "Review focus: task flow, end effector, system interfaces, risk controls, energy strategy, service access, and integration evidence."
            ];

            text.textContent = lines.join("\n");
            if (output) {
                output.hidden = false;
                output.setAttribute("data-state", "ready");
            }
            if (copyButton) {
                copyButton.hidden = false;
            }
        }

        form.addEventListener("submit", buildBrief);
        if (buildButton && buildButton.type !== "submit") {
            buildButton.addEventListener("click", buildBrief);
        }

        if (copyButton) {
            copyButton.addEventListener("click", function () {
                copyText(text.textContent || "").then(function () {
                    var original = copyButton.textContent;
                    copyButton.textContent = "Copied";
                    window.setTimeout(function () {
                        copyButton.textContent = original;
                    }, 1800);
                });
            });
        }
    }

    function copyText(value) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(value);
        }

        return new Promise(function (resolve, reject) {
            var field = document.createElement("textarea");
            field.value = value;
            field.setAttribute("readonly", "");
            field.style.position = "fixed";
            field.style.opacity = "0";
            document.body.appendChild(field);
            field.select();
            var copied = document.execCommand("copy");
            field.remove();
            if (copied) {
                resolve();
            } else {
                reject(new Error("Copy was not available."));
            }
        });
    }

    function robotShapes() {
        return [
            box("mobility", [0, -2.18, 0], [3.15, 0.55, 1.85], "#2a4542"),
            box("mobility", [-1.2, -2.48, 0.78], [0.58, 0.65, 0.48], "#152725"),
            box("mobility", [1.2, -2.48, 0.78], [0.58, 0.65, 0.48], "#152725"),
            box("mobility", [-1.2, -2.48, -0.78], [0.58, 0.65, 0.48], "#152725"),
            box("mobility", [1.2, -2.48, -0.78], [0.58, 0.65, 0.48], "#152725"),
            box("energy", [0, -1.55, 0], [2.2, 0.75, 1.3], "#246f65"),
            box("structure", [0, -0.35, 0], [1.72, 1.65, 1.12], "#d8ebe6"),
            box("compute", [0, 0.35, -0.08], [1.36, 0.55, 0.88], "#173a36"),
            box("perception", [0, 1.08, 0], [1.7, 0.28, 0.82], "#3fdac5"),
            box("perception", [0, 1.52, 0], [1.18, 0.52, 0.66], "#c9f7ef"),
            box("safety", [0, 1.78, 0.34], [1.1, 0.08, 0.12], "#ffcb63"),
            box("manipulation", [-1.05, 0.5, 0], [0.5, 0.56, 0.58], "#bad8d2"),
            box("manipulation", [1.05, 0.5, 0], [0.5, 0.56, 0.58], "#bad8d2"),
            box("manipulation", [-1.45, -0.2, 0], [0.46, 1.22, 0.46], "#a9c9c3", -0.18),
            box("manipulation", [1.45, -0.2, 0], [0.46, 1.22, 0.46], "#a9c9c3", 0.18),
            box("manipulation", [-1.68, -1.08, 0], [0.38, 0.92, 0.38], "#8fb8b1", 0.19),
            box("manipulation", [1.68, -1.08, 0], [0.38, 0.92, 0.38], "#8fb8b1", -0.19),
            box("tooling", [-1.78, -1.68, 0], [0.48, 0.32, 0.52], "#45e5ce"),
            box("tooling", [1.78, -1.68, 0], [0.48, 0.32, 0.52], "#45e5ce"),
            box("safety", [-1.46, -2.16, 0.84], [0.18, 0.22, 0.18], "#ffcb63"),
            box("safety", [1.46, -2.16, 0.84], [0.18, 0.22, 0.18], "#ffcb63")
        ];
    }

    function box(group, center, size, color, rotationZ) {
        return {
            group: group,
            center: center,
            size: size,
            color: color,
            rotationZ: rotationZ || 0
        };
    }

    function drawScene(context, state, shapes) {
        context.clearRect(0, 0, state.width, state.height);
        drawFloor(context, state);

        var faces = [];
        shapes.forEach(function (shape) {
            var vertices = boxVertices(shape, state.explode);
            var screenVertices = vertices.map(function (point) {
                return mapToScreen(point, state);
            });
            var definitions = [
                [0, 1, 2, 3],
                [4, 7, 6, 5],
                [0, 4, 5, 1],
                [3, 2, 6, 7],
                [1, 5, 6, 2],
                [0, 3, 7, 4]
            ];

            definitions.forEach(function (indices, faceIndex) {
                var points = indices.map(function (index) {
                    return screenVertices[index];
                });
                faces.push({
                    points: points,
                    depth: points.reduce(function (total, point) {
                        return total + point.depth;
                    }, 0) / points.length,
                    color: shadeColor(
                        shape.color,
                        shape.group === state.activeGroup
                            ? [0.08, 0.22, 0.02, 0.14, -0.14, -0.06][faceIndex]
                            : [-0.18, -0.08, -0.22, -0.12, -0.3, -0.24][faceIndex]
                    ),
                    active: shape.group === state.activeGroup
                });
            });
        });

        faces.sort(function (a, b) {
            return b.depth - a.depth;
        });

        faces.forEach(function (face) {
            context.beginPath();
            face.points.forEach(function (point, index) {
                if (index === 0) {
                    context.moveTo(point.x, point.y);
                } else {
                    context.lineTo(point.x, point.y);
                }
            });
            context.closePath();
            context.fillStyle = face.color;
            context.fill();
            context.strokeStyle = face.active
                ? "rgba(185,255,243,0.42)"
                : "rgba(205,235,228,0.11)";
            context.lineWidth = face.active ? 1.25 : 0.75;
            context.stroke();
        });

        var crown = mapToScreen([0, 1.82, 0.4], state);
        var glow = context.createRadialGradient(
            crown.x,
            crown.y,
            0,
            crown.x,
            crown.y,
            48 * state.zoom
        );
        glow.addColorStop(0, "rgba(66,230,207,0.44)");
        glow.addColorStop(1, "rgba(66,230,207,0)");
        context.fillStyle = glow;
        context.fillRect(crown.x - 55, crown.y - 55, 110, 110);
    }

    function drawFloor(context, state) {
        var center = mapToScreen([0, -2.64, 0], state);
        context.save();
        context.fillStyle = "rgba(3, 9, 9, 0.32)";
        context.beginPath();
        context.ellipse(
            center.x,
            center.y + 12,
            120 * state.zoom,
            24 * state.zoom,
            0,
            0,
            Math.PI * 2
        );
        context.fill();

        context.strokeStyle = "rgba(112, 218, 201, 0.075)";
        context.lineWidth = 1;
        for (var line = -4; line <= 4; line += 1) {
            drawWorldLine(context, [-4, -2.65, line], [4, -2.65, line], state);
            drawWorldLine(context, [line, -2.65, -4], [line, -2.65, 4], state);
        }
        context.restore();
    }

    function drawWorldLine(context, from, to, state) {
        var a = mapToScreen(from, state);
        var b = mapToScreen(to, state);
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.stroke();
    }

    function boxVertices(shape, explode) {
        var half = shape.size.map(function (value) {
            return value / 2;
        });
        var local = [
            [-half[0], -half[1], -half[2]],
            [half[0], -half[1], -half[2]],
            [half[0], half[1], -half[2]],
            [-half[0], half[1], -half[2]],
            [-half[0], -half[1], half[2]],
            [half[0], -half[1], half[2]],
            [half[0], half[1], half[2]],
            [-half[0], half[1], half[2]]
        ];
        var offset = explodeOffset(shape, explode);
        var sine = Math.sin(shape.rotationZ);
        var cosine = Math.cos(shape.rotationZ);

        return local.map(function (point) {
            var x = point[0] * cosine - point[1] * sine;
            var y = point[0] * sine + point[1] * cosine;
            return [
                x + shape.center[0] + offset[0],
                y + shape.center[1] + offset[1],
                point[2] + shape.center[2] + offset[2]
            ];
        });
    }

    function explodeOffset(shape, amount) {
        var offsets = {
            perception: [0, 0.72, 0],
            compute: [0.52, 0.14, -0.18],
            energy: [-0.52, -0.18, -0.12],
            safety: [0.62, 0.12, 0.5],
            mobility: [0, -0.56, 0],
            manipulation: [0.72, 0.05, 0],
            tooling: [1.05, -0.1, 0],
            structure: [0, 0, 0.58]
        };
        var offset = offsets[shape.group] || [0, 0, 0];
        var x = offset[0];
        if (
            (shape.group === "manipulation" || shape.group === "tooling") &&
            shape.center[0] < 0
        ) {
            x *= -1;
        }
        return [x * amount, offset[1] * amount, offset[2] * amount];
    }

    function mapToScreen(point, state) {
        var cosineY = Math.cos(state.yaw);
        var sineY = Math.sin(state.yaw);
        var x1 = point[0] * cosineY - point[2] * sineY;
        var z1 = point[0] * sineY + point[2] * cosineY;
        var cosineX = Math.cos(state.pitch);
        var sineX = Math.sin(state.pitch);
        var y2 = point[1] * cosineX - z1 * sineX;
        var z2 = point[1] * sineX + z1 * cosineX;
        var camera = 8.2;
        var depth = Math.max(3.4, camera + z2);
        var scale =
            Math.min(state.width, state.height) *
            0.19 *
            state.zoom *
            camera /
            depth;

        return {
            x: state.width * 0.5 + x1 * scale,
            y: state.height * 0.49 - y2 * scale,
            depth: depth
        };
    }

    function positionHotspots(
        root,
        viewer,
        systems,
        systemGroups,
        anchors,
        state
    ) {
        var viewerBounds = viewer.getBoundingClientRect();
        if (!viewerBounds.width || !viewerBounds.height) {
            return;
        }

        root.querySelectorAll(".rbtx-viewer-hotspots [data-rbtx-system]").forEach(
            function (button) {
                var id = button.getAttribute("data-rbtx-system") || "";
                var system = systems.find(function (item) {
                    return item.id === id;
                });
                var group = systemGroups.get(id) || "perception";
                var anchor =
                    system && system.anchor && system.anchor.length === 3
                        ? system.anchor.map(Number)
                        : anchors[group];
                if (!anchor) {
                    return;
                }

                var offset = explodeOffset(
                    {group: group, center: anchor},
                    state.explode
                );
                var point = mapToScreen(
                    [
                        anchor[0] + offset[0],
                        anchor[1] + offset[1],
                        anchor[2] + offset[2]
                    ],
                    state
                );
                var x = clamp(point.x / state.width, 0.08, 0.92) * 100;
                var y = clamp(point.y / state.height, 0.08, 0.88) * 100;
                button.style.left = x.toFixed(2) + "%";
                button.style.top = y.toFixed(2) + "%";
                button.style.opacity = point.depth > 9.2 ? "0.58" : "1";
            }
        );
    }

    function shadeColor(hex, amount) {
        var clean = hex.replace("#", "");
        var red = parseInt(clean.slice(0, 2), 16);
        var green = parseInt(clean.slice(2, 4), 16);
        var blue = parseInt(clean.slice(4, 6), 16);
        var target = amount < 0 ? 0 : 255;
        var weight = Math.abs(amount);

        red = Math.round(red + (target - red) * weight);
        green = Math.round(green + (target - green) * weight);
        blue = Math.round(blue + (target - blue) * weight);
        return "rgb(" + red + "," + green + "," + blue + ")";
    }

    function clamp(value, minimum, maximum) {
        return Math.min(maximum, Math.max(minimum, value));
    }
})();
