(() => {
    'use strict';
    const notice = document.querySelector('[data-login-pause]');
    if (!notice) return;
    const seconds = Number(notice.dataset.retryAfter);
    if (!Number.isFinite(seconds) || seconds <= 0) return;
    const end = Date.now() + seconds * 1000;
    const form = document.querySelector('[data-login-form], #login-form');
    const submit = form && form.querySelector('button[type="submit"], input[type="submit"]');
    const countdown = notice.querySelector('[data-pause-countdown]');
    if (submit) submit.disabled = true;
    // The server enforces the pause. This timer only avoids unnecessary resubmissions.
    // No password is retained and the form is never submitted automatically.
    let timer;
    const tick = () => {
        const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
        if (remaining > 0) {
            if (countdown) countdown.textContent = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`;
            return;
        }
        clearInterval(timer);
        if (submit) submit.disabled = false;
        notice.classList.add('login-pause--ready');
        notice.querySelector('[data-pause-title]').textContent = 'Можно попробовать снова';
        notice.querySelector('[data-pause-message]').textContent = 'Пауза закончилась. Проверьте логин и пароль и повторите вход.';
    };
    // Countdown updates are visual; assistive technology receives only the final message.
    if (countdown) countdown.setAttribute('aria-hidden', 'true');
    tick();
    timer = setInterval(tick, 1000);
    document.addEventListener('visibilitychange', tick);
})();
