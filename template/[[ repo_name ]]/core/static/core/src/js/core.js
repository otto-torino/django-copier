window.core = {}

document.addEventListener("click", (event) => {
    // The [data-cookie-settings] buttons open the Cookie Rulez banner again.
    if (event.target.closest("[data-cookie-settings]")) window.cookierulez?.CookieLayer?.open();
});
