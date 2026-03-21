// Переключение между формами
function showForm(formType) {
  document
    .getElementById("loginForm")
    .classList.toggle("active", formType === "login");
  document
    .getElementById("registerForm")
    .classList.toggle("active", formType === "register");

  // Очищаем ошибки при переключении
  document.getElementById("loginError").textContent = "";
  document.getElementById("registerError").textContent = "";
}

// Обработка формы входа
document
  .getElementById("loginFormElement")
  .addEventListener("submit", async (e) => {
    e.preventDefault();

    const username = document.getElementById("loginUsername").value.trim();
    const password = document.getElementById("loginPassword").value;
    const errorDiv = document.getElementById("loginError");

    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (response.ok) {
        // Сохраняем имя пользователя и редиректим
        localStorage.setItem("username", username);
        window.location.href = "/index.html";
      } else {
        errorDiv.textContent = data.detail || data.error || "Ошибка входа";
      }
    } catch (error) {
      console.error("Login error:", error);
      errorDiv.textContent = "Ошибка подключения к серверу";
    }
  });

// Обработка формы регистрации
document
  .getElementById("registerFormElement")
  .addEventListener("submit", async (e) => {
    e.preventDefault();

    const username = document.getElementById("registerUsername").value.trim();
    const password = document.getElementById("registerPassword").value;
    const confirmPassword = document.getElementById(
      "registerConfirmPassword",
    ).value;
    const errorDiv = document.getElementById("registerError");

    // Валидация на клиенте
    if (password !== confirmPassword) {
      errorDiv.textContent = "Пароли не совпадают";
      return;
    }

    if (username.length < 3) {
      errorDiv.textContent = "Имя пользователя должно быть не менее 3 символов";
      return;
    }

    if (password.length < 6) {
      errorDiv.textContent = "Пароль должен быть не менее 6 символов";
      return;
    }

    try {
      const response = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (response.ok) {
        // Автоматически логиним после регистрации
        localStorage.setItem("username", username);
        window.location.href = "/index.html";
      } else {
        errorDiv.textContent =
          data.detail || data.error || "Ошибка регистрации";
      }
    } catch (error) {
      console.error("Register error:", error);
      errorDiv.textContent = "Ошибка подключения к серверу";
    }
  });
