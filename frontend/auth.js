"use strict";

// SDK amazon-cognito-identity-js 6.3.22, servido localmente (ver vendor/NOTICE.cognito.txt).
window.ServitechAuth = (() => {
  const form = document.getElementById("login-form");
  const fields = document.getElementById("login-fields");
  const challengeForm = document.getElementById("challenge-form");
  const challengeFields = document.getElementById("challenge-fields");
  const answer = document.getElementById("challenge-answer");
  const status = document.getElementById("auth-status");
  const logout = document.getElementById("logout-button");
  // Sin persistir contraseñas o tokens en localStorage/sessionStorage/cookies.
  const values = new Map();
  const storage = {
    setItem: (key, value) => values.set(key, value),
    getItem: (key) => values.get(key) ?? null,
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
  let pool = null;
  let user = null;
  let signedIn = false;
  let challenge = null;
  let callbacks = null;
  let epoch = 0;

  function message(text, state = "error") {
    status.textContent = text;
    status.dataset.state = state;
  }

  function notify() {
    window.dispatchEvent(new Event("servitech-auth-change"));
  }

  function clearSession(text = "Sesión cerrada.") {
    epoch += 1;
    user?.signOut();
    user = null;
    signedIn = false;
    challenge = null;
    callbacks = null;
    values.clear();
    form.reset();
    challengeForm.reset();
    form.hidden = false;
    challengeForm.hidden = true;
    logout.hidden = true;
    fields.disabled = !pool;
    challengeFields.disabled = false;
    message(text, "success");
    notify();
  }

  function fail(error) {
    clearSession();
    message(error?.code === "InvalidPasswordException"
      ? "La contraseña debe tener al menos 12 caracteres, mayúscula, minúscula, número y símbolo."
      : "No se pudo completar el acceso. Revisa tus datos o consulta al administrador.");
  }

  function showChallenge(type) {
    challenge = type;
    form.hidden = true;
    challengeForm.hidden = false;
    challengeFields.disabled = false;
    answer.value = "";
    const password = type === "NEW_PASSWORD_REQUIRED";
    answer.type = password ? "password" : "text";
    answer.autocomplete = password ? "new-password" : "one-time-code";
    answer.inputMode = password ? "text" : "numeric";
    answer.minLength = password ? 12 : 6;
    answer.maxLength = password ? 256 : 6;
    answer.pattern = password ? ".{12,256}" : "[0-9]{6}";
    document.getElementById("challenge-label").textContent = password ? "Nueva contraseña" : "Código de tu aplicación autenticadora";
    message(password ? "Cambia tu contraseña temporal para continuar." : "Ingresa tu código de verificación.", "loading");
    answer.focus();
  }

  try {
    const config = window.SERVITECH_CONFIG;
    if (location.protocol !== "https:" || !config?.userPoolId || !config?.clientId) throw new Error();
    pool = new AmazonCognitoIdentity.CognitoUserPool({
      UserPoolId: config.userPoolId, ClientId: config.clientId, Storage: storage,
    });
  } catch {
    fields.disabled = true;
    message("El acceso todavía no está disponible. Abre el portal HTTPS configurado por el equipo.");
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!pool || fields.disabled || !form.reportValidity()) return;
    fields.disabled = true;
    const attempt = ++epoch;
    user = new AmazonCognitoIdentity.CognitoUser({
      Username: document.getElementById("username").value.trim(), Pool: pool, Storage: storage,
    });
    user.setAuthenticationFlowType("USER_SRP_AUTH");
    callbacks = {
      onSuccess(session) {
        if (attempt !== epoch) return;
        if (!session.isValid()) return fail();
        signedIn = true;
        challenge = null;
        form.reset();
        challengeForm.reset();
        form.hidden = true;
        challengeForm.hidden = true;
        logout.hidden = false;
        message("Sesión iniciada.", "success");
        notify();
      },
      onFailure(error) { if (attempt === epoch) fail(error); },
      newPasswordRequired(_attributes, requiredAttributes) {
        if (attempt !== epoch) return;
        // No reenviar atributos de contacto ni indicadores de verificación.
        if (requiredAttributes?.length) return fail();
        showChallenge("NEW_PASSWORD_REQUIRED");
      },
      totpRequired() { if (attempt === epoch) showChallenge("SOFTWARE_TOKEN_MFA"); },
      mfaRequired() { if (attempt === epoch) fail(); },
      mfaSetup() { if (attempt === epoch) fail(); },
      customChallenge() { if (attempt === epoch) fail(); },
      selectMFAType() { if (attempt === epoch) fail(); },
    };
    const details = new AmazonCognitoIdentity.AuthenticationDetails({
      Username: user.getUsername(), Password: document.getElementById("password").value,
    });
    document.getElementById("password").value = "";
    message("Iniciando sesión…", "loading");
    try { user.authenticateUser(details, callbacks); } catch (error) { fail(error); }
  });

  challengeForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!user || challengeFields.disabled || !challengeForm.reportValidity()) return;
    challengeFields.disabled = true;
    const value = answer.value;
    answer.value = "";
    try {
      if (challenge === "NEW_PASSWORD_REQUIRED") user.completeNewPasswordChallenge(value, {}, callbacks);
      else if (challenge === "SOFTWARE_TOKEN_MFA") user.sendMFACode(value, callbacks, "SOFTWARE_TOKEN_MFA");
      else fail();
    } catch (error) { fail(error); }
  });

  logout.addEventListener("click", () => clearSession());
  document.getElementById("cancel-login").addEventListener("click", () => clearSession("Ingresa tus credenciales."));

  return {
    configured: Boolean(pool),
    isSignedIn: () => signedIn,
    epoch: () => epoch,
    getToken() {
      return new Promise((resolve, reject) => {
        const rejectSession = () => reject(Object.assign(new Error("Inicia sesión para continuar."), { code: "AUTH_REQUIRED" }));
        if (!signedIn || !user) return rejectSession();
        const current = epoch;
        // getSession renueva los tokens vencidos mediante el refresh token del SDK.
        user.getSession((error, session) => {
          if (current !== epoch) return rejectSession();
          if (error || !session?.isValid()) {
            clearSession("La sesión terminó. Vuelve a iniciar sesión.");
            return rejectSession();
          }
          resolve(session.getIdToken().getJwtToken());
        });
      });
    },
  };
})();
