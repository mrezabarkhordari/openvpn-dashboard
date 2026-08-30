/**
 * Theme Toggle System
 * Handles light/dark mode switching with localStorage persistence
 */

(function() {
    'use strict';
    
    const THEME_KEY = 'theme';
    const DARK = 'dark';
    const LIGHT = 'light';
    
    // Get the root element
    const root = document.documentElement;
    
    /**
     * Detect system preference for dark mode
     */
    function getSystemPreference() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return DARK;
        }
        return LIGHT;
    }
    
    /**
     * Get the saved theme or fall back to system preference
     */
    function getSavedTheme() {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === DARK || saved === LIGHT) {
            return saved;
        }
        return getSystemPreference();
    }
    
    /**
     * Apply theme to the document
     */
    function applyTheme(theme) {
        if (theme === DARK) {
            root.setAttribute('data-theme', DARK);
        } else {
            root.removeAttribute('data-theme');
        }
    }
    
    /**
     * Update button icon
     */
    function updateButton(button, theme) {
        if (!button) return;
        
        if (theme === DARK) {
            button.innerHTML = '☀️';
            button.setAttribute('aria-label', 'Switch to light mode');
        } else {
            button.innerHTML = '🌙';
            button.setAttribute('aria-label', 'Switch to dark mode');
        }
    }
    
    /**
     * Toggle between themes
     */
    function toggleTheme(button) {
        const currentTheme = root.getAttribute('data-theme') === DARK ? DARK : LIGHT;
        const newTheme = currentTheme === DARK ? LIGHT : DARK;
        
        applyTheme(newTheme);
        localStorage.setItem(THEME_KEY, newTheme);
        updateButton(button, newTheme);
    }
    
    /**
     * Initialize the theme system
     */
    function init() {
        // Apply saved theme immediately (before DOM ready to prevent flash)
        const savedTheme = getSavedTheme();
        applyTheme(savedTheme);
        
        // Wait for DOM to be ready for button setup
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setupButton);
        } else {
            setupButton();
        }
        
        // Listen for system theme changes
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                // Only auto-switch if user hasn't set a preference
                if (!localStorage.getItem(THEME_KEY)) {
                    const newTheme = e.matches ? DARK : LIGHT;
                    applyTheme(newTheme);
                    const button = document.getElementById('theme-toggle');
                    updateButton(button, newTheme);
                }
            });
        }
    }
    
    /**
     * Set up the toggle button
     */
    function setupButton() {
        const button = document.getElementById('theme-toggle');
        if (!button) return;
        
        const currentTheme = root.getAttribute('data-theme') === DARK ? DARK : LIGHT;
        updateButton(button, currentTheme);
        
        button.addEventListener('click', () => toggleTheme(button));
    }
    
    // Initialize immediately
    init();
})();
