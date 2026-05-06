import {
  createServer,
  createWorld,
  deleteWorld,
  formatBackendError,
  getCurrentUser,
  getServer,
  listWorlds,
  logoutUser,
} from "/js/api.js";

const usernameNode = document.getElementById("username");
const joinServerForm = document.getElementById("joinServerForm");
const joinError = document.getElementById("joinError");
const createWorldForm = document.getElementById("createWorldForm");
const worldSuccess = document.getElementById("worldSuccess");
const worldError = document.getElementById("worldError");
const worldList = document.getElementById("worldList");
const refreshWorldsBtn = document.getElementById("refreshWorldsBtn");
const logoutBtn = document.getElementById("logoutBtn");
const worldTemplate = document.getElementById("worldCardTemplate");

function clearMessages() {
  joinError.textContent = "";
  worldSuccess.textContent = "";
  worldError.textContent = "";
}

function formatTimestamp(timestamp) {
  const date = new Date(timestamp * 1000);
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function openGame(serverCode) {
  window.location.href = `/game.html?server=${encodeURIComponent(serverCode)}`;
}

async function launchServer(worldId, serverInfoNode, serverCardNode) {
  try {
    const server = await createServer(worldId);
    serverInfoNode.innerHTML = `
      <strong>Сервер создан</strong><br>
      Код: <code>${server.server_code}</code><br>
      Игроков: ${server.player_count}/${server.max_players}
    `;
    serverCardNode.classList.remove("hidden");

    const openServerButton = serverCardNode.querySelector(".open-server-button");
    openServerButton.onclick = () => openGame(server.server_code);
  } catch (error) {
    worldError.textContent = formatBackendError(error);
  }
}

async function removeWorld(worldId) {
  try {
    await deleteWorld(worldId);
    worldSuccess.textContent = "Мир удалён.";
    await renderWorlds();
  } catch (error) {
    worldError.textContent = formatBackendError(error);
  }
}

function createDeleteButton(worldId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost-button dark";
  button.textContent = "Удалить мир";
  button.addEventListener("click", () => {
    removeWorld(worldId);
  });
  return button;
}

async function renderWorlds() {
  clearMessages();
  worldList.innerHTML = '<div class="inline-message">Загрузка миров...</div>';

  try {
    const payload = await listWorlds();
    const worlds = payload.worlds || [];

    if (!worlds.length) {
      worldList.innerHTML = '<div class="inline-message">Пока нет миров. Создайте первый.</div>';
      return;
    }

    worldList.innerHTML = "";
    for (const world of worlds) {
      const fragment = worldTemplate.content.cloneNode(true);
      const card = fragment.querySelector(".world-card");
      const nameNode = fragment.querySelector(".world-name");
      const seedNode = fragment.querySelector(".world-seed");
      const metaNode = fragment.querySelector(".world-meta");
      const createServerButton = fragment.querySelector(".create-server-button");
      const worldActions = fragment.querySelector(".world-actions");
      const serverCard = fragment.querySelector(".server-card");
      const serverInfo = fragment.querySelector(".server-info");

      nameNode.textContent = world.world_name;
      seedNode.textContent = `Seed: ${world.world_seed}`;
      metaNode.textContent = `Создан: ${formatTimestamp(world.world_created_at)} · Изменён: ${formatTimestamp(world.world_last_modified)}`;

      createServerButton.addEventListener("click", () => {
        launchServer(world.world_id, serverInfo, serverCard);
      });

      worldActions.appendChild(createDeleteButton(world.world_id));
      worldList.appendChild(card);
    }
  } catch (error) {
    worldList.innerHTML = "";
    worldError.textContent = formatBackendError(error);
  }
}

joinServerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  joinError.textContent = "";
  const serverCode = document.getElementById("serverCodeInput").value.trim().toUpperCase();
  if (!serverCode) {
    joinError.textContent = "Введите код сервера.";
    return;
  }

  try {
    await getServer(serverCode);
    openGame(serverCode);
  } catch (error) {
    joinError.textContent = formatBackendError(error);
  }
});

createWorldForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessages();

  const worldName = document.getElementById("worldNameInput").value.trim();
  const worldSeed = document.getElementById("worldSeedInput").value.trim();

  try {
    await createWorld(worldName, worldSeed);
    worldSuccess.textContent = "Мир успешно создан.";
    createWorldForm.reset();
    await renderWorlds();
  } catch (error) {
    worldError.textContent = formatBackendError(error);
  }
});

refreshWorldsBtn.addEventListener("click", () => {
  renderWorlds();
});

logoutBtn.addEventListener("click", async () => {
  try {
    await logoutUser();
  } finally {
    window.location.href = "/login.html";
  }
});

try {
  const user = await getCurrentUser();
  usernameNode.textContent = user.username;
  await renderWorlds();
} catch (error) {
  window.location.href = "/login.html";
}
