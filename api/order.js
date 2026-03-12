export default async function handler(req, res) {
  // Google Apps Script URL manzilingiz
  const GOOGLE_URL = 'https://script.google.com/macros/s/AKfycbzHxVlbDrKKZN7K-aQiyNUysYNnhJkvWCkSTUX5ceZg/exec';
  const SECRET_TOKEN = "MirBeton_Safe_2026"; // Maxfiy kalit

  if (req.method !== 'POST') return res.status(405).json({ error: 'Faqat POST' });

  try {
    const response = await fetch(GOOGLE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...req.body, secret_token: SECRET_TOKEN })
    });
    const result = await response.json();
    return res.status(200).json(result);
  } catch (err) {
    return res.status(500).json({ success: false, error: err.message });
  }
}
