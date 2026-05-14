import * as THREE from "/vendor/three.module.min.js";
import { io } from "/vendor/socket.io.esm.min.js";
import { GLTFLoader } from "/vendor/GLTFLoader.js";
import { clone as cloneSkinned } from "/vendor/SkeletonUtils.js";
import { formatBackendError, getCurrentUser, getServer } from "/js/api.js";

const BLOCK_COLORS = {
  "воздух": 0x000000,
  "почва": 0x8a603b,
  "песок": 0xd4b16f,
  "вода": 0x4c87d9,
  "кислотная поверхность": 0x8bc34a,
  "дерево": 0x6d4327,
  "листва": 0x4d8a48,
};

const DIRECTION_LABELS = {
  north: "север",
  east: "восток",
  south: "юг",
  west: "запад",
};

const ROBOT_MODEL_URL = "/assets/models/RobotExpressive.glb";
const ROBOT_SCALE = 0.32;
const ROBOT_POSITION_OFFSET = { x: 0, y: -0.1, z: 0 };
const MOVE_ANIMATION_MS = 380;
const TURN_ANIMATION_MS = 220;

const sceneRoot = document.getElementById("sceneRoot");
const connectionChip = document.getElementById("connectionChip");
const statusMessage = document.getElementById("statusMessage");
const scriptMessage = document.getElementById("scriptMessage");
const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const scriptInput = document.getElementById("scriptInput");
const scriptFileInput = document.getElementById("scriptFileInput");
const clearScriptFileBtn = document.getElementById("clearScriptFileBtn");
const scriptFileLabel = document.getElementById("scriptFileLabel");
const runScriptBtn = document.getElementById("runScriptBtn");
const stopScriptBtn = document.getElementById("stopScriptBtn");
const leaveGameBtn = document.getElementById("leaveGameBtn");
const copyServerCodeBtn = document.getElementById("copyServerCodeBtn");
const ALLOWED_SCRIPT_EXTENSIONS = new Set([".bas", ".txt"]);

const stats = {
  coords: document.getElementById("coordsValue"),
  direction: document.getElementById("directionValue"),
  mode: document.getElementById("modeValue"),
  location: document.getElementById("locationValue"),
  health: document.getElementById("healthValue"),
  temperature: document.getElementById("temperatureValue"),
  tick: document.getElementById("tickValue"),
  players: document.getElementById("playersValue"),
};

const labels = {
  serverCode: document.getElementById("serverCodeLabel"),
  playerName: document.getElementById("playerNameLabel"),
  worldName: document.getElementById("worldNameLabel"),
};

const urlParams = new URLSearchParams(window.location.search);
const serverCode = (urlParams.get("server") || "").trim().toUpperCase();

if (!serverCode) {
  window.location.href = "/index.html";
}

labels.serverCode.textContent = serverCode;

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(sceneRoot.clientWidth, sceneRoot.clientHeight);
renderer.shadowMap.enabled = true;
sceneRoot.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x92c5df);
scene.fog = new THREE.Fog(0x92c5df, 40, 120);

const camera = new THREE.PerspectiveCamera(
  55,
  sceneRoot.clientWidth / Math.max(sceneRoot.clientHeight, 1),
  0.1,
  500,
);
const cameraLookTarget = new THREE.Vector3();
const cameraDesiredPosition = new THREE.Vector3();

const clock = new THREE.Clock();

const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
scene.add(ambientLight);

const sunLight = new THREE.DirectionalLight(0xfff2cf, 1.2);
sunLight.position.set(20, 35, 10);
sunLight.castShadow = true;
scene.add(sunLight);

const grid = new THREE.GridHelper(160, 32, 0x28341f, 0x32412a);
grid.position.y = 0;
scene.add(grid);

const blocksGroup = new THREE.Group();
const playersGroup = new THREE.Group();
scene.add(blocksGroup);
scene.add(playersGroup);

const state = {
  currentUser: null,
  server: null,
  self: null,
  players: [],
  tick: 0,
  blockMeshes: new Map(),
  playerVisuals: new Map(),
  chatKeys: new Set(),
  robotAsset: null,
  robotAssetFailed: false,
  selectedScriptFileName: null,
};

function toSceneCoordinates(coordinates, yOffset = 0) {
  return [-coordinates[0], coordinates[1] + yOffset, coordinates[2]];
}

function coordinateKey(coordinates) {
  return coordinates.join(":");
}

function getBlockColor(blockName) {
  return BLOCK_COLORS[blockName] ?? 0x9c8d79;
}

function rotationFromDirection(directionKey) {
  switch (directionKey) {
    case "east":
      return -Math.PI / 2;
    case "south":
      return Math.PI;
    case "west":
      return Math.PI / 2;
    case "north":
    default:
      return 0;
  }
}

function setStatus(message, kind = "") {
  statusMessage.textContent = message;
  statusMessage.style.color =
    kind === "error" ? "#ff9f91" : kind === "success" ? "#a7df9b" : "";
}

function setScriptStatus(message, kind = "") {
  scriptMessage.textContent = message;
  scriptMessage.style.color =
    kind === "error" ? "#ff9f91" : kind === "success" ? "#a7df9b" : "";
}

function getScriptExtension(fileName) {
  const dotIndex = fileName.lastIndexOf(".");
  return dotIndex >= 0 ? fileName.slice(dotIndex).toLowerCase() : "";
}

function updateSelectedScriptFile(fileName = null) {
  state.selectedScriptFileName = fileName;
  scriptFileLabel.textContent = fileName || "Файл не выбран";
}

function clearSelectedScriptFile() {
  updateSelectedScriptFile(null);
  scriptFileInput.value = "";
}

function setConnectionState(text, kind = "neutral") {
  if (!connectionChip) {
    return;
  }
  connectionChip.textContent = text;
  if (kind === "ok") {
    connectionChip.style.color = "#b7efb5";
  } else if (kind === "error") {
    connectionChip.style.color = "#ffc0b6";
  } else {
    connectionChip.style.color = "";
  }
}

function normalizeAngle(angle) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

function lerpAngle(current, target, alpha) {
  const diff = normalizeAngle(target - current);
  return current + diff * alpha;
}

function createFallbackPlayerModel(isSelf) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.8, 1.3, 0.8),
    new THREE.MeshStandardMaterial({ color: isSelf ? 0xffd166 : 0xe25b45, roughness: 0.6 }),
  );
  body.position.y = 0.65;
  body.castShadow = true;
  group.add(body);

  const marker = new THREE.Mesh(
    new THREE.ConeGeometry(0.24, 0.55, 6),
    new THREE.MeshStandardMaterial({ color: 0xfff3dc }),
  );
  marker.position.set(0, 0.9, 0.65);
  marker.rotation.x = Math.PI / 2;
  group.add(marker);
  return group;
}

function createSelfMarker() {
  const marker = new THREE.Mesh(
    new THREE.RingGeometry(0.55, 0.72, 32),
    new THREE.MeshBasicMaterial({ color: 0xffd166, side: THREE.DoubleSide }),
  );
  marker.rotation.x = -Math.PI / 2;
  marker.position.y = 0.03;
  return marker;
}

async function loadRobotAsset() {
  try {
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(ROBOT_MODEL_URL);
    state.robotAsset = {
      scene: gltf.scene,
      animations: gltf.animations || [],
    };
    syncPlayers(state.players);
  } catch (error) {
    state.robotAssetFailed = true;
    setStatus("Не удалось загрузить модель робота, использую запасную модель.", "error");
  }
}

function buildRobotClone() {
  const model = cloneSkinned(state.robotAsset.scene);
  model.scale.setScalar(ROBOT_SCALE);
  model.traverse((node) => {
    if (node.isMesh) {
      node.castShadow = true;
      node.receiveShadow = true;
    }
  });

  const box = new THREE.Box3().setFromObject(model);
  model.position.y -= box.min.y;
  model.position.x += ROBOT_POSITION_OFFSET.x;
  model.position.y += ROBOT_POSITION_OFFSET.y;
  model.position.z += ROBOT_POSITION_OFFSET.z;
  return model;
}

function setAction(visual, actionName, fadeDuration = 0.18) {
  if (!visual.actions || !visual.actions[actionName] || visual.activeActionName === actionName) {
    return;
  }

  const nextAction = visual.actions[actionName];
  const previousAction = visual.activeAction;
  visual.activeActionName = actionName;
  visual.activeAction = nextAction;

  if (previousAction && previousAction !== nextAction) {
    previousAction.fadeOut(fadeDuration);
  }

  nextAction
    .reset()
    .setEffectiveTimeScale(1)
    .setEffectiveWeight(1)
    .fadeIn(fadeDuration)
    .play();
}

function createPlayerVisual(player) {
  const isSelf = player.user_id === state.currentUser?.id;
  const root = new THREE.Group();
  let mixer = null;
  let actions = null;
  let activeAction = null;
  let activeActionName = "";

  if (state.robotAsset) {
    const model = buildRobotClone();
    root.add(model);

    mixer = new THREE.AnimationMixer(model);
    actions = {};
    for (const clip of state.robotAsset.animations) {
      actions[clip.name] = mixer.clipAction(clip);
    }

    if (actions.Idle) {
      activeAction = actions.Idle;
      activeActionName = "Idle";
      activeAction.play();
    } else {
      const [fallbackClipName] = Object.keys(actions);
      if (fallbackClipName) {
        activeAction = actions[fallbackClipName];
        activeActionName = fallbackClipName;
        activeAction.play();
      }
    }
  } else {
    root.add(createFallbackPlayerModel(isSelf));
  }

  if (isSelf) {
    root.add(createSelfMarker());
  }

  root.position.set(...toSceneCoordinates(player.coordinates, -1));
  root.rotation.y = rotationFromDirection(player.direction_key);
  playersGroup.add(root);

  return {
    root,
    mixer,
    actions,
    activeAction,
    activeActionName,
    targetPosition: root.position.clone(),
    targetRotation: root.rotation.y,
    movingUntil: 0,
  };
}

function disposePlayerVisual(visual) {
  playersGroup.remove(visual.root);
}

function upsertBlockMesh(block) {
  const key = coordinateKey(block.coordinates);
  let mesh = state.blockMeshes.get(key);

  if (!mesh) {
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const material = new THREE.MeshStandardMaterial({
      color: getBlockColor(block.location),
      roughness: 0.92,
      metalness: 0.04,
    });
    mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    blocksGroup.add(mesh);
    state.blockMeshes.set(key, mesh);
  }

  const [sceneX, sceneY, sceneZ] = toSceneCoordinates(block.coordinates);
  mesh.position.set(sceneX, sceneY, sceneZ);
  mesh.material.color.setHex(getBlockColor(block.location));
}

function syncBlocks(nearLocations = []) {
  const nextKeys = new Set();

  for (const block of nearLocations) {
    if (!block || !Array.isArray(block.coordinates) || block.location === "воздух") {
      continue;
    }
    nextKeys.add(coordinateKey(block.coordinates));
    upsertBlockMesh(block);
  }

  for (const [key, mesh] of state.blockMeshes.entries()) {
    if (nextKeys.has(key)) {
      continue;
    }
    blocksGroup.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
    state.blockMeshes.delete(key);
  }
}

function syncPlayers(players = []) {
  if (!state.robotAsset && !state.robotAssetFailed) {
    return;
  }

  const nextKeys = new Set();
  const now = performance.now();

  for (const player of players) {
    const key = player.player_id;
    nextKeys.add(key);

    let visual = state.playerVisuals.get(key);
    if (!visual) {
      visual = createPlayerVisual(player);
      state.playerVisuals.set(key, visual);
    }

    const [sceneX, sceneY, sceneZ] = toSceneCoordinates(player.coordinates, -1);
    const nextPosition = new THREE.Vector3(sceneX, sceneY, sceneZ);
    const nextRotation = rotationFromDirection(player.direction_key);

    const moved = visual.targetPosition.distanceToSquared(nextPosition) > 0.0001;
    const turned = Math.abs(normalizeAngle(nextRotation - visual.targetRotation)) > 0.001;

    visual.targetPosition.copy(nextPosition);
    visual.targetRotation = nextRotation;

    if (moved) {
      visual.movingUntil = Math.max(visual.movingUntil, now + MOVE_ANIMATION_MS);
    } else if (turned) {
      visual.movingUntil = Math.max(visual.movingUntil, now + TURN_ANIMATION_MS);
    }
  }

  for (const [key, visual] of state.playerVisuals.entries()) {
    if (nextKeys.has(key)) {
      continue;
    }
    disposePlayerVisual(visual);
    state.playerVisuals.delete(key);
  }
}

function rebuildPlayerVisuals() {
  for (const visual of state.playerVisuals.values()) {
    disposePlayerVisual(visual);
  }
  state.playerVisuals.clear();
  syncPlayers(state.players);
}

function updatePlayerVisuals(deltaSeconds) {
  const now = performance.now();
  const positionAlpha = Math.min(1, deltaSeconds * 8);
  const rotationAlpha = Math.min(1, deltaSeconds * 10);

  for (const visual of state.playerVisuals.values()) {
    visual.root.position.lerp(visual.targetPosition, positionAlpha);
    visual.root.rotation.y = lerpAngle(visual.root.rotation.y, visual.targetRotation, rotationAlpha);

    if (visual.mixer) {
      if (visual.actions?.Walking && visual.actions?.Idle) {
        setAction(visual, now < visual.movingUntil ? "Walking" : "Idle");
      }
      visual.mixer.update(deltaSeconds);
    }
  }
}

function updateCamera() {
  if (!state.self?.coordinates) {
    return;
  }

  const selfVisual = state.playerVisuals.get(state.self.player_id);
  const anchor = selfVisual?.root?.position;
  const x = anchor?.x ?? toSceneCoordinates(state.self.coordinates, -1)[0];
  const y = anchor?.y ?? toSceneCoordinates(state.self.coordinates, -1)[1];
  const z = anchor?.z ?? toSceneCoordinates(state.self.coordinates, -1)[2];
  const offsets = {
    north: [0, 6, -10],
    east: [10, 6, 0],
    south: [0, 6, 10],
    west: [-10, 6, 0],
  };

  const [dx, dy, dz] = offsets[state.self.direction_key] || offsets.north;
  cameraDesiredPosition.set(x + dx, y + dy, z + dz);
  cameraLookTarget.set(
    THREE.MathUtils.lerp(cameraLookTarget.x, x, 0.12),
    THREE.MathUtils.lerp(cameraLookTarget.y, y + 1.7, 0.12),
    THREE.MathUtils.lerp(cameraLookTarget.z, z, 0.12),
  );
  camera.position.lerp(cameraDesiredPosition, 0.12);
  camera.lookAt(cameraLookTarget);
}

function updateHud() {
  if (!state.self) {
    return;
  }

  stats.coords.textContent = state.self.coordinates.join(", ");
  stats.direction.textContent = DIRECTION_LABELS[state.self.direction_key] || state.self.direction;
  stats.mode.textContent = state.self.mode || state.self.mode_key;
  stats.location.textContent = state.self.location;
  stats.health.textContent = String(state.self.health);
  stats.temperature.textContent = `${Number(state.self.temperature).toFixed(1)} °C`;
  stats.tick.textContent = String(state.tick);
  stats.players.textContent = String(state.players.length);

  labels.playerName.textContent = state.self.username || state.currentUser?.username || "...";
  labels.worldName.textContent = state.server?.world_name || state.world?.world_name || "...";
}

function applySelfState(nextState) {
  if (!nextState) {
    return;
  }
  const firstState = !state.self;
  state.self = nextState;
  if (firstState) {
    const [x, y, z] = toSceneCoordinates(nextState.coordinates, -1);
    cameraLookTarget.set(x, y + 1.7, z);
    camera.position.set(x, y + 6, z - 10);
  }
  syncBlocks(nextState.nearLocations || []);
  updateHud();
  updateCamera();
}

function appendChatMessage(message) {
  const key = `${message.timestamp}:${message.player_id}:${message.message}`;
  if (state.chatKeys.has(key)) {
    return;
  }
  state.chatKeys.add(key);

  const node = document.createElement("article");
  node.className = "chat-message";
  node.innerHTML = `
    <div class="chat-author">${message.username}</div>
    <div class="chat-text">${message.message || ""}</div>
  `;
  chatMessages.appendChild(node);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hydrateChat(messages = []) {
  chatMessages.innerHTML = "";
  state.chatKeys.clear();
  for (const message of messages) {
    appendChatMessage(message);
  }
}

function resizeRenderer() {
  const width = sceneRoot.clientWidth;
  const height = sceneRoot.clientHeight;
  renderer.setSize(width, height);
  camera.aspect = width / Math.max(height, 1);
  camera.updateProjectionMatrix();
}

window.addEventListener("resize", resizeRenderer);

const socket = io({
  path: "/socket.io",
  withCredentials: true,
  transports: ["websocket"],
  query: { server_code: serverCode },
});

socket.on("connect", () => {
  setConnectionState("Соединение установлено", "ok");
  setStatus("Игровой сокет подключён.", "success");
});

socket.on("disconnect", () => {
  setConnectionState("Соединение потеряно", "error");
  setStatus("Соединение с сервером разорвано.", "error");
});

socket.on("connect_error", (error) => {
  setConnectionState("Ошибка подключения", "error");
  setStatus(error.message || "Не удалось подключиться к игровому серверу.", "error");
});

socket.on("allInfo", (payload) => {
  applySelfState(payload);
});

socket.on("state", (payload) => {
  applySelfState(payload);
});

socket.on("world_state", (payload) => {
  state.world = payload.world;
  state.players = payload.players || [];
  syncPlayers(state.players);
  hydrateChat(payload.chat_history || []);
  if (payload.self) {
    applySelfState(payload.self);
  }
  if (payload.world?.world_name) {
    labels.worldName.textContent = payload.world.world_name;
  }
});

socket.on("tick_state", (payload) => {
  state.tick = payload.tick || 0;
  state.players = payload.players || [];
  syncPlayers(state.players);
  applySelfState(payload.self);
});

socket.on("world_tick", (payload) => {
  if (Array.isArray(payload.players)) {
    state.players = payload.players;
    syncPlayers(state.players);
    updateHud();
  }
});

socket.on("player_joined", (payload) => {
  setStatus(`Игрок ${payload.username} подключился к серверу.`, "success");
});

socket.on("player_left", (payload) => {
  setStatus(`Игрок ${payload.username} вышел из сервера.`, "success");
});

socket.on("chat_message", (payload) => {
  appendChatMessage(payload);
});

socket.on("script_result", (payload) => {
  if (payload.status === "success") {
    setScriptStatus("Скрипт выполнен успешно.", "success");
  } else if (payload.status === "stopped") {
    setScriptStatus("Скрипт остановлен.", "success");
  } else {
    setScriptStatus(payload.error || "Ошибка выполнения скрипта.", "error");
  }
});

socket.on("basic_error", (payload) => {
  setScriptStatus(payload?.error || "BASIC завершился с ошибкой.", "error");
});

socket.on("runtime_error", (payload) => {
  setScriptStatus(payload?.error || "Ошибка игрового рантайма.", "error");
});

scriptFileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files || [];
  if (!file) {
    clearSelectedScriptFile();
    return;
  }

  const extension = getScriptExtension(file.name);
  if (!ALLOWED_SCRIPT_EXTENSIONS.has(extension)) {
    clearSelectedScriptFile();
    setScriptStatus("Поддерживаются только файлы .bas и .txt.", "error");
    return;
  }

  try {
    const scriptText = await file.text();
    scriptInput.value = scriptText;
    updateSelectedScriptFile(file.name);
    setScriptStatus(`Файл ${file.name} загружен в редактор.`, "success");
  } catch (error) {
    clearSelectedScriptFile();
    setScriptStatus("Не удалось прочитать выбранный файл.", "error");
  }
});

clearScriptFileBtn.addEventListener("click", () => {
  clearSelectedScriptFile();
  setScriptStatus("Выбранный файл сброшен.");
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) {
    return;
  }
  socket.emit("chat_message", { message });
  chatInput.value = "";
});

runScriptBtn.addEventListener("click", () => {
  const scriptText = scriptInput.value.trim();
  if (!scriptText) {
    setScriptStatus("Введите BASIC-скрипт перед запуском.", "error");
    return;
  }
  setScriptStatus("Скрипт отправлен на сервер...");
  if (state.selectedScriptFileName) {
    socket.emit("exec", {
      script_name: state.selectedScriptFileName,
      script_content: scriptText,
    });
    return;
  }
  socket.emit("exec", scriptText);
});

stopScriptBtn.addEventListener("click", () => {
  setScriptStatus("Отправляю запрос на остановку...");
  socket.emit("stop_script");
});

leaveGameBtn.addEventListener("click", () => {
  socket.disconnect();
  window.location.href = "/index.html";
});

copyServerCodeBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(serverCode);
    setStatus("Код сервера скопирован.", "success");
  } catch (error) {
    setStatus("Не удалось скопировать код.", "error");
  }
});

let lastActionAt = 0;
function canSendAction() {
  const now = Date.now();
  if (now - lastActionAt < 120) {
    return false;
  }
  lastActionAt = now;
  return true;
}

window.addEventListener("keydown", (event) => {
  const tagName = document.activeElement?.tagName;
  if (tagName === "INPUT" || tagName === "TEXTAREA" || event.repeat) {
    return;
  }

  const key = event.key.toLowerCase();
  if (!canSendAction()) {
    return;
  }

  if (key === "w" || key === "arrowup") {
    socket.emit("move", "forward");
  } else if (key === "s" || key === "arrowdown") {
    socket.emit("move", "backward");
  } else if (key === "a") {
    socket.emit("move", "left");
  } else if (key === "d") {
    socket.emit("move", "right");
  } else if (key === "q" || key === "arrowleft") {
    socket.emit("turn", "left");
  } else if (key === "e" || key === "arrowright") {
    socket.emit("turn", "right");
  } else if (key === "h") {
    socket.emit("heal");
  } else if (key === "r") {
    socket.emit("restart");
  } else {
    lastActionAt = 0;
  }
});

function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  updatePlayerVisuals(delta);
  updateCamera();
  renderer.render(scene, camera);
}

resizeRenderer();
animate();
loadRobotAsset();

try {
  state.currentUser = await getCurrentUser();
  state.server = await getServer(serverCode);
  labels.playerName.textContent = state.currentUser.username;
  labels.worldName.textContent = state.server.world_name;
  rebuildPlayerVisuals();
} catch (error) {
  setStatus(formatBackendError(error), "error");
  setConnectionState("Доступ запрещён", "error");
  setTimeout(() => {
    window.location.href = "/index.html";
  }, 1200);
}
