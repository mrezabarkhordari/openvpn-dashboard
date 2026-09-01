/**
 * Theme Toggle System
 * Light/dark mode with localStorage persistence (Tailwind `class="dark"`).
 */

(function() {
    'use strict';

    const THEME_KEY = 'theme';
    const DARK = 'dark';
    const LIGHT = 'light';
    const root = document.documentElement;

    function getSystemPreference() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return DARK;
        }
        return LIGHT;
    }

    function getSavedTheme() {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === DARK || saved === LIGHT) {
            return saved;
        }
        return getSystemPreference();
    }

    function applyTheme(theme) {
        if (theme === DARK) {
            root.classList.add(DARK);
        } else {
            root.classList.remove(DARK);
        }
    }

    function updateButton(button, theme) {
        if (!button) return;
        const icon = button.querySelector('[data-lucide]');
        if (icon) {
            icon.setAttribute('data-lucide', theme === DARK ? 'sun' : 'moon');
            if (window.lucide) {
                window.lucide.createIcons();
            }
        }
        button.setAttribute('aria-label', theme === DARK ? 'Switch to light mode' : 'Switch to dark mode');
    }

    function toggleTheme(button) {
        const currentTheme = root.classList.contains(DARK) ? DARK : LIGHT;
        const newTheme = currentTheme === DARK ? LIGHT : DARK;
        applyTheme(newTheme);
        localStorage.setItem(THEME_KEY, newTheme);
        updateButton(button, newTheme);
    }

    function setupButton() {
        const button = document.getElementById('theme-toggle');
        if (!button) return;
        const currentTheme = root.classList.contains(DARK) ? DARK : LIGHT;
        updateButton(button, currentTheme);
        button.addEventListener('click', function() {
            toggleTheme(button);
        });
    }

    function init() {
        applyTheme(getSavedTheme());

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setupButton);
        } else {
            setupButton();
        }

        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
                if (!localStorage.getItem(THEME_KEY)) {
                    const newTheme = e.matches ? DARK : LIGHT;
                    applyTheme(newTheme);
                    updateButton(document.getElementById('theme-toggle'), newTheme);
                }
            });
        }
    }

    init();
})();
