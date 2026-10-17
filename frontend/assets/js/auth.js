// Sign-in, sign-up, forgot-password and reset-password pages share this script.
const $ = (selector) => document.querySelector(selector);

function showError(message) {
  const box = $("#form-error");
  box.textContent = message;
  box.hidden = false;
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await response.json(); } catch (_) { /* non-JSON error page */ }
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? "Check the details you entered." : data.detail;
    throw new Error(detail || "Something went wrong. Try again.");
  }
  return data;
}

// Wrap a submit handler: clears errors, locks the button while working, shows failures.
function onSubmit(form, handler) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    $("#form-error").hidden = true;
    const button = form.querySelector("button[type=submit]");
    const label = button.textContent;
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span>';
    try {
      await handler();
    } catch (error) {
      showError(error.message);
      button.disabled = false;
      button.textContent = label;
    }
  });
}

document.querySelectorAll("[data-toggle]").forEach((toggle) => {
  toggle.addEventListener("click", () => {
    const input = document.getElementById(toggle.dataset.toggle);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    toggle.textContent = show ? "Hide" : "Show";
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
});

const hint = $("#pw-hint");
if (hint && $("#password")) {
  $("#password").addEventListener("input", (event) => {
    const long = event.target.value.length >= 8;
    hint.classList.toggle("ok", long);
    hint.textContent = long ? "Good. That works." : "At least 8 characters.";
  });
}

// ---- sign in
const loginForm = $("#login-form");
if (loginForm) {
  const params = new URLSearchParams(location.search);
  if (params.get("reset")) {
    $("#notice").textContent = "Password updated. Sign in with your new password.";
    $("#notice").hidden = false;
  }
  onSubmit(loginForm, async () => {
    await post("/api/auth/login", {
      username: loginForm.elements.username.value,
      password: loginForm.elements.password.value,
    });
    location.replace("/dashboard");
  });
}

// ---- sign up
const registerForm = $("#register-form");
if (registerForm) {
  onSubmit(registerForm, async () => {
    const password = registerForm.elements.password.value;
    if (password.length < 8) throw new Error("Use at least 8 characters for your password.");
    await post("/api/auth/register", {
      username: registerForm.elements.username.value,
      email: registerForm.elements.email.value,
      password,
    });
    location.replace("/dashboard");
  });
}

// ---- forgot password
const forgotForm = $("#forgot-form");
if (forgotForm) {
  onSubmit(forgotForm, async () => {
    const email = forgotForm.elements.email.value.trim();
    const result = await post("/api/auth/forgot", { email });
    $("#sent-to").textContent = email;
    $("#no-mail").hidden = result.email_enabled !== false;
    $("#ask").hidden = true;
    $("#done").hidden = false;
  });
}

// ---- reset password (arrives from the email link)
const resetForm = $("#reset-form");
if (resetForm) {
  const token = new URLSearchParams(location.search).get("token") || "";
  history.replaceState(null, "", location.pathname); // keep the token out of the address bar
  fetch(`/api/auth/reset/check?token=${encodeURIComponent(token)}`)
    .then((response) => response.json())
    .then((result) => { $(result.valid ? "#choose" : "#bad").hidden = false; })
    .catch(() => { $("#bad").hidden = false; });
  onSubmit(resetForm, async () => {
    const password = resetForm.elements.password.value;
    if (password !== resetForm.elements.confirm.value) throw new Error("The two passwords don't match.");
    await post("/api/auth/reset", { token, password });
    location.replace("/login?reset=1");
  });
}
