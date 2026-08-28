import * as THREE from "../vendor/three.module.min.js";

const canvas = document.getElementById("pipeline-scene");
const payloadNode = document.getElementById("pipeline-scene-data");

if (canvas && payloadNode) {
    let data = {};
    try {
        data = JSON.parse(payloadNode.textContent);
    } catch (error) {
        console.error("3D pipeline payload is invalid.", error);
    }

    const fallback = document.getElementById("webgl-fallback");
    const webglContext = canvas.getContext("webgl2", {
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
    });

    if (!webglContext) {
        if (fallback) fallback.hidden = false;
    } else {
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x020812, 0.045);

        const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
        camera.position.set(0, 4.55, 13.25);
        camera.lookAt(0, 0.3, 0);

        const renderer = new THREE.WebGLRenderer({
            canvas,
            context: webglContext,
            alpha: true,
            antialias: true,
            powerPreference: "high-performance",
        });
        renderer.setClearColor(0x000000, 0);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.2;

        const world = new THREE.Group();
        world.rotation.x = -0.05;
        world.scale.setScalar(1.08);
        scene.add(world);

        scene.add(new THREE.AmbientLight(0x4c7892, 0.62));
        const cyanLight = new THREE.PointLight(0x20d9ff, 25, 14, 2);
        cyanLight.position.set(-2, 3, 4);
        scene.add(cyanLight);
        const purpleLight = new THREE.PointLight(0xa855f7, 22, 12, 2);
        purpleLight.position.set(4, 1, 2);
        scene.add(purpleLight);
        const rimLight = new THREE.DirectionalLight(0x88eaff, 1.5);
        rimLight.position.set(-4, 7, 7);
        scene.add(rimLight);

        const glowTextures = new Map();
        const animatedNodes = [];
        const flowParticles = [];
        const clickableObjects = [];
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        function numberLabel(value) {
            return new Intl.NumberFormat("ko-KR").format(value || 0);
        }

        function glowTexture(color) {
            if (glowTextures.has(color)) return glowTextures.get(color);
            const textureCanvas = document.createElement("canvas");
            textureCanvas.width = 256;
            textureCanvas.height = 256;
            const context = textureCanvas.getContext("2d");
            const gradient = context.createRadialGradient(128, 128, 3, 128, 128, 128);
            gradient.addColorStop(0, "rgba(255,255,255,0.92)");
            gradient.addColorStop(0.12, color);
            gradient.addColorStop(0.42, `${color}55`);
            gradient.addColorStop(1, "rgba(0,0,0,0)");
            context.fillStyle = gradient;
            context.fillRect(0, 0, 256, 256);
            const texture = new THREE.CanvasTexture(textureCanvas);
            texture.colorSpace = THREE.SRGBColorSpace;
            glowTextures.set(color, texture);
            return texture;
        }

        function makeGlow(color, scale = 2.6, opacity = 0.58) {
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
                map: glowTexture(color),
                color: 0xffffff,
                transparent: true,
                opacity,
                blending: THREE.AdditiveBlending,
                depthWrite: false,
            }));
            sprite.scale.set(scale, scale, scale);
            return sprite;
        }

        function makeLabel(title, subtitle, color) {
            const labelCanvas = document.createElement("canvas");
            labelCanvas.width = 768;
            labelCanvas.height = 192;
            const context = labelCanvas.getContext("2d");
            context.clearRect(0, 0, 768, 192);
            const background = context.createLinearGradient(90, 0, 678, 0);
            background.addColorStop(0, "rgba(2,8,18,0)");
            background.addColorStop(0.25, "rgba(4,16,30,0.88)");
            background.addColorStop(0.75, "rgba(4,16,30,0.88)");
            background.addColorStop(1, "rgba(2,8,18,0)");
            context.fillStyle = background;
            context.fillRect(55, 20, 658, 145);
            context.strokeStyle = `${color}99`;
            context.lineWidth = 2;
            context.beginPath();
            context.moveTo(130, 25);
            context.lineTo(638, 25);
            context.stroke();
            context.textAlign = "center";
            context.fillStyle = "#e8faff";
            context.font = "700 46px Arial";
            context.fillText(title, 384, 88);
            context.fillStyle = color;
            context.font = "600 28px Consolas";
            context.fillText(subtitle, 384, 132);
            const texture = new THREE.CanvasTexture(labelCanvas);
            texture.colorSpace = THREE.SRGBColorSpace;
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
                map: texture,
                transparent: true,
                depthTest: false,
                depthWrite: false,
            }));
            sprite.scale.set(3.2, 0.8, 1);
            return sprite;
        }

        function createStageNode({ title, value, color, position, geometry = "icosa", url = "" }) {
            const node = new THREE.Group();
            node.position.copy(position);

            const colorValue = new THREE.Color(color);
            const geometryObject = geometry === "octa"
                ? new THREE.OctahedronGeometry(0.58, 2)
                : new THREE.IcosahedronGeometry(0.58, 3);
            const core = new THREE.Mesh(geometryObject, new THREE.MeshStandardMaterial({
                color: colorValue.clone().multiplyScalar(0.4),
                emissive: colorValue,
                emissiveIntensity: 0.85,
                metalness: 0.72,
                roughness: 0.23,
                transparent: true,
                opacity: 0.9,
                wireframe: geometry === "octa",
            }));
            node.add(core);

            const innerCore = new THREE.Mesh(
                new THREE.IcosahedronGeometry(0.29, 2),
                new THREE.MeshBasicMaterial({ color: 0xe7fbff, transparent: true, opacity: 0.78 })
            );
            node.add(innerCore);

            const ringMaterial = new THREE.MeshBasicMaterial({
                color: colorValue,
                transparent: true,
                opacity: 0.48,
                blending: THREE.AdditiveBlending,
                depthWrite: false,
            });
            const ringOne = new THREE.Mesh(new THREE.TorusGeometry(0.82, 0.015, 8, 96), ringMaterial);
            ringOne.rotation.x = Math.PI / 2.8;
            node.add(ringOne);
            const ringTwo = new THREE.Mesh(new THREE.TorusGeometry(0.98, 0.012, 8, 96), ringMaterial.clone());
            ringTwo.rotation.y = Math.PI / 2.3;
            node.add(ringTwo);

            const halo = makeGlow(color, 2.9, 0.4);
            halo.position.z = -0.3;
            node.add(halo);

            const verticalBeam = new THREE.Mesh(
                new THREE.CylinderGeometry(0.09, 0.32, 2.8, 20, 1, true),
                new THREE.MeshBasicMaterial({
                    color: colorValue,
                    transparent: true,
                    opacity: 0.08,
                    blending: THREE.AdditiveBlending,
                    depthWrite: false,
                    side: THREE.DoubleSide,
                })
            );
            verticalBeam.position.y = -1.22;
            node.add(verticalBeam);

            const label = makeLabel(title, numberLabel(value), color);
            label.position.y = 1.25;
            node.add(label);

            if (url) {
                node.traverse((object) => {
                    if (object.isMesh || object.isSprite) {
                        object.userData.url = url;
                        clickableObjects.push(object);
                    }
                });
            }

            animatedNodes.push({ node, core, innerCore, ringOne, ringTwo, halo, phase: Math.random() * Math.PI * 2 });
            world.add(node);
            return node;
        }

        function createDatabaseNode({ title, value, color, position, url, shape }) {
            const node = createStageNode({ title, value, color, position, geometry: shape, url });
            const baseMaterial = new THREE.MeshStandardMaterial({
                color: new THREE.Color(color).multiplyScalar(0.3),
                emissive: new THREE.Color(color),
                emissiveIntensity: 0.55,
                metalness: 0.82,
                roughness: 0.18,
                transparent: true,
                opacity: 0.88,
            });
            if (shape === "octa") {
                for (let index = -1; index <= 1; index += 1) {
                    const disk = new THREE.Mesh(new THREE.CylinderGeometry(0.68, 0.68, 0.18, 48), baseMaterial.clone());
                    disk.position.y = index * 0.25;
                    node.add(disk);
                }
            } else {
                const shell = new THREE.Mesh(new THREE.DodecahedronGeometry(0.72, 0), baseMaterial);
                shell.rotation.set(0.3, 0.2, 0.1);
                node.add(shell);
            }
            node.traverse((object) => {
                if (object.isMesh || object.isSprite) {
                    object.userData.url = url;
                    if (!clickableObjects.includes(object)) clickableObjects.push(object);
                }
            });
            return node;
        }

        function makeCurve(start, end, lift = 0, depth = 0) {
            const midpoint = start.clone().lerp(end, 0.5);
            midpoint.y += lift;
            midpoint.z += depth;
            return new THREE.CatmullRomCurve3([start, midpoint, end], false, "catmullrom", 0.42);
        }

        function createFlow(curve, color, particleCount = 18, speed = 0.085) {
            const tube = new THREE.Mesh(
                new THREE.TubeGeometry(curve, 90, 0.025, 8, false),
                new THREE.MeshBasicMaterial({
                    color,
                    transparent: true,
                    opacity: 0.3,
                    blending: THREE.AdditiveBlending,
                    depthWrite: false,
                })
            );
            world.add(tube);

            const positions = new Float32Array(particleCount * 3);
            const offsets = Array.from({ length: particleCount }, (_, index) => index / particleCount);
            const pointsGeometry = new THREE.BufferGeometry();
            pointsGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
            const points = new THREE.Points(pointsGeometry, new THREE.PointsMaterial({
                color,
                size: 0.105,
                transparent: true,
                opacity: 0.95,
                blending: THREE.AdditiveBlending,
                depthWrite: false,
                sizeAttenuation: true,
            }));
            world.add(points);
            flowParticles.push({ curve, points, positions, offsets, speed });
        }

        const positions = {
            legacy: new THREE.Vector3(-5.4, 0.35, 0),
            standard: new THREE.Vector3(-2.35, 0.35, 0),
            normalize: new THREE.Vector3(0.75, 0.35, 0),
            mysql: new THREE.Vector3(4.55, 1.85, -0.1),
            mongo: new THREE.Vector3(4.55, -1.38, -0.1),
        };

        createStageNode({ title: "LEGACY", value: data.legacy, color: "#20d9ff", position: positions.legacy, geometry: "octa" });
        createStageNode({ title: "STANDARDIZE", value: data.standardized, color: "#38a6ff", position: positions.standard });
        createStageNode({ title: "NORMALIZE", value: data.normalized, color: "#15e6c1", position: positions.normalize });
        createDatabaseNode({ title: "MYSQL ACCEPTED", value: data.mysqlLoaded, color: "#15e6c1", position: positions.mysql, url: canvas.dataset.mysqlUrl, shape: "octa" });
        createDatabaseNode({ title: "MONGODB REJECTED", value: data.mongoLoaded, color: "#a855f7", position: positions.mongo, url: canvas.dataset.mongoUrl, shape: "dodeca" });

        createFlow(makeCurve(positions.legacy, positions.standard, 0.55, 0.35), "#20d9ff", 24, 0.095);
        createFlow(makeCurve(positions.standard, positions.normalize, 0.45, -0.2), "#38a6ff", 20, 0.088);
        createFlow(makeCurve(positions.normalize, positions.mysql, 1.15, 0.55), "#15e6c1", 24, 0.1);
        createFlow(makeCurve(positions.standard, positions.mongo, -1.45, -0.8), "#a855f7", 14, 0.075);
        createFlow(makeCurve(positions.normalize, positions.mongo, -0.8, 0.65), "#f59e0b", 10, 0.068);

        const platformMaterial = new THREE.MeshBasicMaterial({
            color: 0x20d9ff,
            transparent: true,
            opacity: 0.14,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
        });
        [2.7, 3.8, 5.15].forEach((radius, index) => {
            const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.015, 8, 160), platformMaterial.clone());
            ring.rotation.x = Math.PI / 2;
            ring.position.set(0, -2.35, -0.7);
            ring.material.opacity = 0.18 - index * 0.04;
            world.add(ring);
        });

        const starCount = 700;
        const starPositions = new Float32Array(starCount * 3);
        for (let index = 0; index < starCount; index += 1) {
            starPositions[index * 3] = (Math.random() - 0.5) * 18;
            starPositions[index * 3 + 1] = (Math.random() - 0.5) * 10;
            starPositions[index * 3 + 2] = (Math.random() - 0.5) * 8 - 1;
        }
        const starsGeometry = new THREE.BufferGeometry();
        starsGeometry.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
        const stars = new THREE.Points(starsGeometry, new THREE.PointsMaterial({
            color: 0x3da6cc,
            size: 0.018,
            transparent: true,
            opacity: 0.48,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
        }));
        scene.add(stars);

        const raycaster = new THREE.Raycaster();
        const pointer = new THREE.Vector2(2, 2);
        let dragging = false;
        let moved = false;
        let pointerStart = { x: 0, y: 0 };
        let targetRotationY = 0;
        let targetRotationX = -0.05;

        const updatePointer = (event) => {
            const rect = canvas.getBoundingClientRect();
            pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        };

        canvas.addEventListener("pointerdown", (event) => {
            dragging = true;
            moved = false;
            pointerStart = { x: event.clientX, y: event.clientY };
            canvas.setPointerCapture(event.pointerId);
        });
        canvas.addEventListener("pointermove", (event) => {
            updatePointer(event);
            if (dragging) {
                const deltaX = event.clientX - pointerStart.x;
                const deltaY = event.clientY - pointerStart.y;
                if (Math.abs(deltaX) + Math.abs(deltaY) > 3) moved = true;
                targetRotationY = THREE.MathUtils.clamp(targetRotationY + deltaX * 0.0018, -0.18, 0.18);
                targetRotationX = THREE.MathUtils.clamp(targetRotationX + deltaY * 0.0012, -0.11, 0.07);
                pointerStart = { x: event.clientX, y: event.clientY };
            }
            raycaster.setFromCamera(pointer, camera);
            const hovered = raycaster.intersectObjects(clickableObjects, false)[0];
            canvas.style.cursor = hovered ? "pointer" : dragging ? "grabbing" : "grab";
        });
        canvas.addEventListener("pointerup", (event) => {
            dragging = false;
            canvas.releasePointerCapture(event.pointerId);
            if (!moved) {
                updatePointer(event);
                raycaster.setFromCamera(pointer, camera);
                const selected = raycaster.intersectObjects(clickableObjects, false)[0];
                if (selected?.object.userData.url) window.location.href = selected.object.userData.url;
            }
        });
        canvas.addEventListener("pointerleave", () => {
            dragging = false;
            pointer.set(2, 2);
        });

        function resize() {
            const rect = canvas.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            renderer.setSize(rect.width, rect.height, false);
            camera.aspect = rect.width / rect.height;
            camera.updateProjectionMatrix();
        }
        const resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(canvas);
        resize();

        const animationStartedAt = performance.now();
        renderer.setAnimationLoop(() => {
            if (document.hidden) return;
            const elapsed = (performance.now() - animationStartedAt) / 1000;
            const motionScale = reducedMotion ? 0.18 : 1;

            world.rotation.y += (targetRotationY - world.rotation.y) * 0.055;
            world.rotation.x += (targetRotationX - world.rotation.x) * 0.055;
            if (!dragging) {
                targetRotationY *= 0.996;
                targetRotationX += (-0.05 - targetRotationX) * 0.003;
            }

            if (!reducedMotion) {
                const orbitPhase = elapsed * 0.105;
                camera.position.x = Math.sin(orbitPhase) * 0.86;
                camera.position.y = 4.55 + Math.sin(elapsed * 0.14) * 0.16;
                camera.position.z = 13.25 + Math.cos(orbitPhase) * 0.3;
            } else {
                camera.position.set(0, 4.55, 13.25);
            }
            camera.lookAt(0, 0.28, 0);

            animatedNodes.forEach((entry, index) => {
                entry.core.rotation.x = elapsed * (0.18 + index * 0.014) * motionScale;
                entry.core.rotation.y = elapsed * (0.25 + index * 0.012) * motionScale;
                entry.innerCore.rotation.y = -elapsed * 0.45 * motionScale;
                entry.ringOne.rotation.z = elapsed * 0.24 * motionScale + entry.phase;
                entry.ringTwo.rotation.x = elapsed * 0.19 * motionScale + entry.phase;
                const pulse = 1 + Math.sin(elapsed * 1.7 + entry.phase) * 0.07 * motionScale;
                entry.halo.scale.setScalar(2.9 * pulse);
            });

            flowParticles.forEach((flow) => {
                flow.offsets.forEach((offset, index) => {
                    const t = (offset + elapsed * flow.speed * motionScale) % 1;
                    const point = flow.curve.getPointAt(t);
                    flow.positions[index * 3] = point.x;
                    flow.positions[index * 3 + 1] = point.y;
                    flow.positions[index * 3 + 2] = point.z;
                });
                flow.points.geometry.attributes.position.needsUpdate = true;
            });

            stars.rotation.y = elapsed * 0.006 * motionScale;
            renderer.render(scene, camera);
        });

        window.addEventListener("beforeunload", () => {
            renderer.setAnimationLoop(null);
            resizeObserver.disconnect();
            renderer.dispose();
            glowTextures.forEach((texture) => texture.dispose());
        }, { once: true });
    }
}
