import { useEffect, useRef } from "react";
import * as THREE from "three";

// The gate, rendered.
//
// This is not ambient decoration. Each mote is a cart arriving from a seller,
// carrying an amount. The plane is the gate. A cart whose amount sits under the
// mandate's ceiling passes through and turns green; one that does not is turned
// back at the plane and turns red. The proportion you see is the proportion the
// benchmark actually produced, so the picture cannot flatter the product.
//
// Every number below is deterministic: a small LCG seeded once, no Math.random,
// so the scene is identical on every load and in every screenshot.

const NAVY = new THREE.Color("#192839");
const BLUE = new THREE.Color("#305eff");
const GREEN = new THREE.Color("#16794a");
const RED = new THREE.Color("#f0263c");

const COUNT = 220;
const GATE_X = 0;
const SPAWN_X = -17;
const EXIT_X = 15;

/** A linear congruential generator: repeatable pseudo-randomness, no library. */
function makeRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

export default function GateScene({ allowedShare = 0.55 }) {
  const host = useRef(null);
  const progress = useRef(0);

  useEffect(() => {
    const el = host.current;
    if (!el) return;

    // A machine that cannot run WebGL should get a quiet page, not a crash.
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog("#ffffff", 22, 46);

    const camera = new THREE.PerspectiveCamera(
      42,
      el.clientWidth / el.clientHeight,
      0.1,
      100,
    );
    camera.position.set(13, 6, 20);
    camera.lookAt(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.15);
    key.position.set(-8, 12, 10);
    scene.add(key);

    // --- the gate ---------------------------------------------------------
    const gate = new THREE.Group();
    const pane = new THREE.Mesh(
      new THREE.PlaneGeometry(13, 13),
      new THREE.MeshBasicMaterial({
        color: BLUE,
        transparent: true,
        opacity: 0.055,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    pane.rotation.y = Math.PI / 2;
    gate.add(pane);

    const frame = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.PlaneGeometry(13, 13)),
      new THREE.LineBasicMaterial({
        color: BLUE,
        transparent: true,
        opacity: 0.5,
      }),
    );
    frame.rotation.y = Math.PI / 2;
    gate.add(frame);

    // A lattice, so the plane reads as something a cart has to get through.
    const lines = [];
    for (let i = -6; i <= 6; i += 2) {
      lines.push(0, i, -6.5, 0, i, 6.5, 0, -6.5, i, 0, 6.5, i);
    }
    const lattice = new THREE.LineSegments(
      new THREE.BufferGeometry().setAttribute(
        "position",
        new THREE.Float32BufferAttribute(lines, 3),
      ),
      new THREE.LineBasicMaterial({
        color: BLUE,
        transparent: true,
        opacity: 0.16,
      }),
    );
    gate.add(lattice);
    scene.add(gate);

    // --- the carts --------------------------------------------------------
    const random = makeRandom(20260905);
    const carts = new THREE.InstancedMesh(
      new THREE.IcosahedronGeometry(0.19, 0),
      new THREE.MeshStandardMaterial({ roughness: 0.45, metalness: 0.05 }),
      COUNT,
    );
    carts.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

    const state = [];
    for (let i = 0; i < COUNT; i += 1) {
      state.push({
        x: SPAWN_X + random() * (EXIT_X - SPAWN_X),
        y: (random() - 0.5) * 11,
        z: (random() - 0.5) * 11,
        speed: 0.035 + random() * 0.055,
        allowed: random() < allowedShare,
        turned: false,
        spin: random() * Math.PI * 2,
      });
    }

    const dummy = new THREE.Object3D();
    const colour = new THREE.Color();
    const paint = (cart) => {
      if (cart.turned) return RED;
      if (cart.x > GATE_X) return GREEN;
      return NAVY;
    };
    for (let i = 0; i < COUNT; i += 1) {
      carts.setColorAt(i, colour.copy(paint(state[i])));
    }
    scene.add(carts);

    // --- loop -------------------------------------------------------------
    let frameId = 0;
    const clock = new THREE.Clock();

    const tick = () => {
      const dt = Math.min(clock.getDelta(), 0.05) * 60;
      const p = progress.current;

      for (let i = 0; i < COUNT; i += 1) {
        const cart = state[i];
        const before = cart.x;
        cart.x += cart.speed * dt * (cart.turned ? -1.35 : 1);

        // The moment of decision: a refused cart never crosses the plane.
        if (
          !cart.turned &&
          before <= GATE_X &&
          cart.x > GATE_X &&
          !cart.allowed
        ) {
          cart.turned = true;
          cart.x = GATE_X;
        }
        if (cart.x > EXIT_X || cart.x < SPAWN_X) {
          cart.x = SPAWN_X;
          cart.turned = false;
          cart.y = (random() - 0.5) * 11;
          cart.z = (random() - 0.5) * 11;
        }

        cart.spin += 0.01 * dt;
        dummy.position.set(cart.x, cart.y, cart.z);
        dummy.rotation.set(cart.spin, cart.spin * 0.6, 0);
        const near = 1 - Math.min(Math.abs(cart.x - GATE_X) / 3, 1);
        dummy.scale.setScalar(1 + near * 0.5);
        dummy.updateMatrix();
        carts.setMatrixAt(i, dummy.matrix);
        carts.setColorAt(i, colour.copy(paint(cart)));
      }
      carts.instanceMatrix.needsUpdate = true;
      if (carts.instanceColor) carts.instanceColor.needsUpdate = true;

      // Scroll swings the camera from side-on (watching carts arrive) to
      // face-on (looking through the gate), which is the shift the copy makes.
      const angle = 0.55 - p * 1.15;
      const radius = 24 - p * 5;
      camera.position.set(
        Math.sin(angle) * radius,
        6 - p * 3.4,
        Math.cos(angle) * radius,
      );
      // Aimed left of the gate so the action sits in the right of the frame,
      // clear of the headline rather than behind it.
      camera.lookAt(-1.5, 0, 0);
      gate.rotation.z = p * 0.06;

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(tick);
    };

    // Respect a viewer who has asked for less movement: one still frame.
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) renderer.render(scene, camera);
    else frameId = requestAnimationFrame(tick);

    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      progress.current = max > 0 ? Math.min(window.scrollY / max, 1) : 0;
    };
    const onResize = () => {
      if (!el.clientWidth) return;
      camera.aspect = el.clientWidth / el.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(el.clientWidth, el.clientHeight);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    onScroll();

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      carts.geometry.dispose();
      carts.material.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, [allowedShare]);

  return <div className="scene" ref={host} aria-hidden="true" />;
}
