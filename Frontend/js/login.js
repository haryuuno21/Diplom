import {
  formatBackendError,
  getCurrentUser,
  loginUser,
  registerUser,
} from "/js/api.js";

const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const showLoginBtn = document.getElementById("showLoginBtn");
const showRegisterBtn = document.getElementById("showRegisterBtn");
const loginError = document.getElementById("loginError");
const registerError = document.getElementById("registerError");

function showForm(formType) {
  const loginActive = formType === "login";
  loginForm.classList.toggle("active", loginActive);
  registerForm.classList.toggle("active", !loginActive);
  showLoginBtn.classList.toggle("active", loginActive);
  showRegisterBtn.classList.toggle("active", !loginActive);
  loginError.textContent = "";
  registerError.textContent = "";
}

showLoginBtn.addEventListener("click", () => showForm("login"));
showRegisterBtn.addEventListener("click", () => showForm("register"));

document.getElementById("loginFormElement").addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";

  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;

  try {
    await loginUser(username, password);
    window.location.href = "/index.html";
  } catch (error) {
    loginError.textContent = formatBackendError(error);
  }
});

document.getElementById("registerFormElement").addEventListener("submit", async (event) => {
  event.preventDefault();
  registerError.textContent = "";

  const username = document.getElementById("registerUsername").value.trim();
  const password = document.getElementById("registerPassword").value;
  const confirmPassword = document.getElementById("registerConfirmPassword").value;

  if (password !== confirmPassword) {
    registerError.textContent = "Пароли не совпадают.";
    return;
  }

  try {
    await registerUser(username, password);
    window.location.href = "/index.html";
  } catch (error) {
    registerError.textContent = formatBackendError(error);
  }
});

try {
  await getCurrentUser();
  window.location.href = "/index.html";
} catch (error) {
  if (error?.status && error.status !== 401) {
    loginError.textContent = formatBackendError(error);
  }
}
