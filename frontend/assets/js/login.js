const form = document.querySelector("#login-form");
const error = document.querySelector("#login-error");
const setupMessage = document.querySelector("#setup-message");

async function checkLoginSetup() {
  const response = await fetch("/api/auth/status");
  const status = await response.json();
  if (status.authenticated) {
    location.replace("/dashboard");
    return;
  }
  if (!status.configured) {
    setupMessage.hidden = false;
    setupMessage.textContent = "Login is not configured yet. Set ADMIN_PASSWORD and AUTH_SECRET in your environment, then restart Synapse.";
    form.querySelector("button").disabled = true;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.elements.username.value,
        password: form.elements.password.value,
      }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || "Unable to sign in.");
    }
    location.replace("/dashboard");
  } catch (cause) {
    error.textContent = cause.message;
    error.hidden = false;
    button.disabled = false;
  }
});

checkLoginSetup().catch((cause) => {
  setupMessage.hidden = false;
  setupMessage.textContent = `Could not check login setup: ${cause.message}`;
});
