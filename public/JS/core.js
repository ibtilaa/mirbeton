// Barcha sahifalar uchun umumiy Telegram WebApp init
const tg = window.Telegram.WebApp;
const params = new URLSearchParams(window.location.search);
const userId = params.get('user_id');

tg.expand();

// Umumiy API chaqiruv funksiyasi
async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    if (data) options.body = JSON.stringify(data);
    
    const response = await fetch(endpoint, options);
    return await response.json();
}