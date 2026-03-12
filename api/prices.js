export default async function handler(req, res) {
  // Google Sheets CSV (Publish to web) havolangiz
  const SHEET_CSV_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQLHoy9zrKAi5cvDHmLR7_yKQ03AGcUKBEVlbhatpE0g2kfwuU6z9V_V_IISI1HPpwm3D1GJKGxAngF/pub?gid=61862596&single=true&output=csv';

  try {
    const response = await fetch(SHEET_CSV_URL);
    if (!response.ok) throw new Error('Jadval topilmadi');
    const data = await response.text();
    
    res.setHeader('Content-Type', 'text/csv');
    return res.status(200).send(data);
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
