import * as THREE from "../vendor/three.module.min.js";

const canvas = document.getElementById("gold-constellation");
const payloadNode = document.getElementById("gold-scene-data");

if (canvas && payloadNode) {
    let payload = { managers: [] };
    try {
        payload = JSON.parse(payloadNode.textContent);
    } catch (error) {
        console.error("Gold 3D payload is invalid.", error);
    }

    const fallback = document.getElementById("gold-webgl-fallback");
    const tooltip = document.getElementById("gold-node-tooltip");
    const context = canvas.getContext("webgl2", {
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
    });

    if (!context) {
        if (fallback) fallback.hidden = false;
    } else {
        const managers = Array.isArray(payload.managers) ? payload.managers : [];
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x020711, 0.045);

        const camera = new THREE.PerspectiveCamera(43, 1, 0.1, 100);
        camera.position.set(0, 1.2, 10.8);
        camera.lookAt(0, 0, 0);

        const renderer = new THREE.WebGLRenderer({
            canvas,
            context,
            alpha: true,
            antialias: true,
            powerPreference: "high-performance",
        });
        renderer.setClearColor(0x000000, 0);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.25;

        const world = new THREE.Group();
        world.rotation.x = -0.08;
        scene.add(world);

        scene.add(new THREE.AmbientLight(0x67818f, 0.55));
        const goldLight = new THREE.PointLight(0xf7c948, 42, 14, 2);
        goldLight.position.set(0, 1.2, 3.3);
        scene.add(goldLight);
        const cyanLight = new THREE.PointLight(0x20d9ff, 25, 14, 2);
        cyanLight.position.set(-4, 3, 2);
        scene.add(cyanLight);
        const purpleLight = new THREE.PointLight(0xa855f7, 18, 12, 2);
        purpleLight.position.set(4, -2, 1);
        scene.add(purpleLight);

        const goldMaterial = new THREE.MeshStandardMaterial({
            color: 0x5c4711,
            emissive: 0xf7c948,
            emissiveIntensity: 0.72,
            metalness: 0.92,
            roughness: 0.16,
            transparent: true,
            opacity: 0.95,
        });
        const medallion = new THREE.Mesh(new THREE.IcosahedronGeometry(0.72, 4), goldMaterial);
        world.add(medallion);
        const medallionWire = new THREE.Mesh(
            new THREE.IcosahedronGeometry(0.92, 2),
            new THREE.MeshBasicMaterial({
                color: 0xf7c948,
                wireframe: true,
                transparent: true,
                opacity: 0.17,
                blending: THREE.AdditiveBlending,
                depthWrite: false,
            })
        );
        world.add(medallionWire);

        const orbitRings = [];
        [1.35, 2.25, 3.25, 4.2].forEach((radius, index) => {
            const ring = new THREE.Mesh(
                new THREE.TorusGeometry(radius, 0.012 + index * 0.002, 8, 160),
                new THREE.MeshBasicMaterial({
                    color: index % 2 ? 0x20d9ff : 0xf7c948,
                    transparent: true,
                    opacity: 0.2 - index * 0.025,
                    blending: THREE.AdditiveBlending,
                    depthWrite: false,
                })
            );
            ring.rotation.x = Math.PI / 2 + (index - 1.5) * 0.12;
            ring.rotation.y = index * 0.19;
            world.add(ring);
            orbitRings.push(ring);
        });

        const labelCanvas = document.createElement("canvas");
        labelCanvas.width = 768;
        labelCanvas.height = 224;
        const labelContext = labelCanvas.getContext("2d");
        labelContext.textAlign = "center";
        labelContext.fillStyle = "rgba(2, 8, 18, 0.84)";
        labelContext.fillRect(120, 28, 528, 160);
        labelContext.strokeStyle = "rgba(247, 201, 72, 0.72)";
        labelContext.strokeRect(121, 29, 526, 158);
        labelContext.fillStyle = "#fff3b7";
        labelContext.font = "700 48px Arial";
        labelContext.fillText("GOLD MEDALLION", 384, 96);
        labelContext.fillStyle = "#f7c948";
        labelContext.font = "600 31px Consolas";
        labelContext.fillText(`${managers.length} MANAGER FEATURES`, 384, 148);
        const labelTexture = new THREE.CanvasTexture(labelCanvas);
        labelTexture.colorSpace = THREE.SRGBColorSpace;
        const label = new THREE.Sprite(new THREE.SpriteMaterial({
            map: labelTexture,
            transparent: true,
            depthTest: false,
            depthWrite: false,
        }));
        label.position.set(0, 1.65, 0);
        label.scale.set(3.5, 1.02, 1);
        world.add(label);

        const departmentPalette = [0x20d9ff, 0xa855f7, 0x15e6c1, 0xff6b91, 0x5b8cff, 0xf7c948, 0x32e68c, 0xff8a4c];
        const departments = Array.from(new Set(managers.map((manager) => manager.department)));
        const departmentColors = new Map(departments.map((name, index) => [name, departmentPalette[index % departmentPalette.length]]));
        const managerMeshes = [];
        const managerGroups = [];
        const maxTenure = Math.max(1, ...managers.map((manager) => Number(manager.tenureDays || 0)));
        const goldenAngle = Math.PI * (3 - Math.sqrt(5));

        managers.forEach((manager, index) => {
            const departmentIndex = Math.max(0, departments.indexOf(manager.department));
            const departmentAngle = (departmentIndex / Math.max(1, departments.length)) * Math.PI * 2;
            const localAngle = index * goldenAngle;
            const radius = 2.0 + (index % 4) * 0.64 + Math.min(0.6, Number(manager.areaCount || 0) * 0.045);
            const angle = departmentAngle + localAngle * 0.16;
            const tenureRatio = Number(manager.tenureDays || 0) / maxTenure;
            const position = new THREE.Vector3(
                Math.cos(angle) * radius,
                (tenureRatio - 0.5) * 3.4 + Math.sin(localAngle) * 0.32,
                Math.sin(angle) * radius * 0.54 - 0.35,
            );

            const group = new THREE.Group();
            group.position.copy(position);
            const unassigned = Number(manager.areaCount || 0) === 0;
            const color = unassigned
                ? 0xf59e0b
                : manager.reassignmentRequired
                    ? 0xf7c948
                    : departmentColors.get(manager.department) || 0x20d9ff;
            const size = 0.13 + Math.min(0.26, Number(manager.areaCount || 0) * 0.022);
            const mesh = new THREE.Mesh(
                new THREE.SphereGeometry(size, 20, 16),
                new THREE.MeshStandardMaterial({
                    color: new THREE.Color(color).multiplyScalar(manager.active ? 0.65 : 0.28),
                    emissive: color,
                    emissiveIntensity: manager.active ? 0.72 : 0.22,
                    metalness: 0.68,
                    roughness: 0.25,
                    transparent: true,
                    opacity: manager.active ? 0.95 : 0.5,
                })
            );
            mesh.userData.manager = manager;
            group.add(mesh);
            managerMeshes.push(mesh);

            if (manager.reassignmentRequired) {
                const ring = new THREE.Mesh(
                    new THREE.TorusGeometry(size * 1.7, 0.012, 6, 48),
                    new THREE.MeshBasicMaterial({
                        color: 0xf7c948,
                        transparent: true,
                        opacity: 0.72,
                        blending: THREE.AdditiveBlending,
                        depthWrite: false,
                    })
                );
                ring.rotation.x = Math.PI / 2;
                group.add(ring);
                group.userData.ring = ring;
            }

            const line = new THREE.Line(
                new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), position]),
                new THREE.LineBasicMaterial({
                    color,
                    transparent: true,
                    opacity: unassigned ? 0.12 : 0.07,
                    blending: THREE.AdditiveBlending,
                    depthWrite: false,
                })
            );
            world.add(line);
            world.add(group);
            managerGroups.push({ group, mesh, baseY: position.y, phase: index * 0.37 });
        });

        const starCount = 650;
        const starPositions = new Float32Array(starCount * 3);
        for (let index = 0; index < starCount; index += 1) {
            starPositions[index * 3] = (Math.random() - 0.5) * 16;
            starPositions[index * 3 + 1] = (Math.random() - 0.5) * 9;
            starPositions[index * 3 + 2] = (Math.random() - 0.5) * 8 - 1;
        }
        const starGeometry = new THREE.BufferGeometry();
        starGeometry.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
        const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({
            color: 0x8fcde2,
            size: 0.025,
            transparent: true,
            opacity: 0.38,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
        }));
        scene.add(stars);

        const raycaster = new THREE.Raycaster();
        const pointer = new THREE.Vector2(2, 2);
        let hovered = null;
        let dragging = false;
        let moved = false;
        let lastX = 0;
        let lastY = 0;
        let targetRotationY = 0;
        let targetRotationX = -0.08;
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        function updatePointer(event) {
            const rect = canvas.getBoundingClientRect();
            pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        }

        canvas.addEventListener("pointerdown", (event) => {
            dragging = true;
            moved = false;
            lastX = event.clientX;
            lastY = event.clientY;
            canvas.setPointerCapture(event.pointerId);
        });
        canvas.addEventListener("pointermove", (event) => {
            updatePointer(event);
            if (!dragging) return;
            const deltaX = event.clientX - lastX;
            const deltaY = event.clientY - lastY;
            moved ||= Math.abs(deltaX) + Math.abs(deltaY) > 2;
            targetRotationY += deltaX * 0.006;
            targetRotationX = Math.max(-0.58, Math.min(0.42, targetRotationX + deltaY * 0.004));
            lastX = event.clientX;
            lastY = event.clientY;
        });
        canvas.addEventListener("pointerup", (event) => {
            dragging = false;
            if (!moved && hovered?.userData.manager) {
                window.dispatchEvent(new CustomEvent("gold:manager-selected", {
                    detail: { managerId: hovered.userData.manager.managerId },
                }));
            }
            canvas.releasePointerCapture(event.pointerId);
        });
        canvas.addEventListener("pointerleave", () => {
            pointer.set(2, 2);
            dragging = false;
            if (tooltip) tooltip.hidden = true;
        });
        canvas.addEventListener("wheel", (event) => {
            event.preventDefault();
            camera.position.z = Math.max(7.2, Math.min(14.5, camera.position.z + event.deltaY * 0.008));
        }, { passive: false });

        function resize() {
            const width = Math.max(1, canvas.clientWidth);
            const height = Math.max(1, canvas.clientHeight);
            renderer.setSize(width, height, false);
            camera.aspect = width / height;
            camera.updateProjectionMatrix();
        }
        const resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(canvas);
        resize();

        const clock = new THREE.Clock();
        function animate() {
            const elapsed = clock.getElapsedTime();
            if (!dragging && !reducedMotion) targetRotationY += 0.0008;
            world.rotation.y += (targetRotationY - world.rotation.y) * 0.045;
            world.rotation.x += (targetRotationX - world.rotation.x) * 0.045;
            medallion.rotation.y = elapsed * 0.22;
            medallion.rotation.x = Math.sin(elapsed * 0.4) * 0.13;
            medallionWire.rotation.y = -elapsed * 0.13;
            orbitRings.forEach((ring, index) => {
                ring.rotation.z = elapsed * (0.018 + index * 0.006) * (index % 2 ? -1 : 1);
            });
            managerGroups.forEach(({ group, ring, baseY, phase }, index) => {
                group.position.y = baseY + Math.sin(elapsed * 0.7 + phase) * 0.035;
                if (group.userData.ring) group.userData.ring.rotation.z = elapsed * (0.45 + (index % 3) * 0.1);
            });
            stars.rotation.y = elapsed * 0.006;

            raycaster.setFromCamera(pointer, camera);
            const intersection = raycaster.intersectObjects(managerMeshes, false)[0];
            const nextHovered = intersection?.object || null;
            if (hovered !== nextHovered) {
                if (hovered) hovered.scale.setScalar(1);
                hovered = nextHovered;
                if (hovered) hovered.scale.setScalar(1.65);
            }
            canvas.style.cursor = hovered ? "pointer" : dragging ? "grabbing" : "grab";
            if (tooltip) {
                if (hovered?.userData.manager) {
                    const manager = hovered.userData.manager;
                    tooltip.textContent = `${manager.managerId}\n${manager.department} · ${manager.position}\nAREA ${manager.areaCount} · SCORE ${manager.workloadScore}\n${manager.priority || "NORMAL"} · RATIO ${manager.workloadRatio}`;
                    tooltip.hidden = false;
                    tooltip.style.left = `${((pointer.x + 1) / 2) * canvas.clientWidth + 14}px`;
                    tooltip.style.top = `${((1 - pointer.y) / 2) * canvas.clientHeight + 14}px`;
                } else {
                    tooltip.hidden = true;
                }
            }

            renderer.render(scene, camera);
            window.requestAnimationFrame(animate);
        }
        animate();
    }
}
