PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','merchant','customer')),
 suspended INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS businesses (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users, category_id INTEGER NOT NULL REFERENCES categories,
 name TEXT NOT NULL, description TEXT NOT NULL, address TEXT NOT NULL, latitude REAL NOT NULL CHECK(latitude BETWEEN -85 AND 85),
 longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180), rate INTEGER NOT NULL CHECK(rate BETWEEN 1 AND 1000),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected'))
);
CREATE INDEX IF NOT EXISTS business_map ON businesses(status,latitude,longitude);
CREATE INDEX IF NOT EXISTS business_owner ON businesses(owner_id);
CREATE TABLE IF NOT EXISTS offers (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses, title TEXT NOT NULL,
 description TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS rewards (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses, title TEXT NOT NULL,
 cost INTEGER NOT NULL CHECK(cost>0), active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS purchases (
 id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses, user_id INTEGER NOT NULL REFERENCES users,
 receipt TEXT NOT NULL, fils INTEGER NOT NULL CHECK(fils>0), points INTEGER NOT NULL CHECK(points>=0), token_hash TEXT NOT NULL UNIQUE,
 expires_at INTEGER NOT NULL, verified_at INTEGER, UNIQUE(business_id,receipt)
);
CREATE INDEX IF NOT EXISTS purchases_customer ON purchases(user_id);
CREATE TABLE IF NOT EXISTS accounts (
 user_id INTEGER NOT NULL REFERENCES users, business_id INTEGER NOT NULL REFERENCES businesses,
 balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0), PRIMARY KEY(user_id,business_id)
);
CREATE TABLE IF NOT EXISTS redemptions (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users, reward_id INTEGER NOT NULL REFERENCES rewards,
 code TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL, cost INTEGER NOT NULL CHECK(cost>0),
 claimed_at INTEGER, UNIQUE(user_id,request_id)
);
CREATE TABLE IF NOT EXISTS challenges (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, starts_at INTEGER NOT NULL,
 ends_at INTEGER NOT NULL CHECK(ends_at>starts_at), goal INTEGER NOT NULL CHECK(goal>0), bonus INTEGER NOT NULL CHECK(bonus>0)
);
CREATE TABLE IF NOT EXISTS challenge_businesses (
 challenge_id INTEGER NOT NULL REFERENCES challenges, business_id INTEGER NOT NULL REFERENCES businesses,
 PRIMARY KEY(challenge_id,business_id)
);
CREATE TABLE IF NOT EXISTS participants (
 id INTEGER PRIMARY KEY, challenge_id INTEGER NOT NULL REFERENCES challenges, user_id INTEGER NOT NULL REFERENCES users,
 joined_at INTEGER NOT NULL, completed_at INTEGER, UNIQUE(challenge_id,user_id)
);
CREATE TABLE IF NOT EXISTS challenge_progress (
 participant_id INTEGER NOT NULL REFERENCES participants, business_id INTEGER NOT NULL REFERENCES businesses,
 purchase_id INTEGER NOT NULL REFERENCES purchases, PRIMARY KEY(participant_id,business_id)
);
CREATE TABLE IF NOT EXISTS platform_accounts (
 user_id INTEGER PRIMARY KEY REFERENCES users, balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0)
);
CREATE TABLE IF NOT EXISTS ledger (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users, business_id INTEGER REFERENCES businesses,
 purchase_id INTEGER UNIQUE REFERENCES purchases, redemption_id INTEGER UNIQUE REFERENCES redemptions,
 participant_id INTEGER UNIQUE REFERENCES participants, delta INTEGER NOT NULL, created_at INTEGER NOT NULL,
 CHECK((purchase_id IS NOT NULL)+(redemption_id IS NOT NULL)+(participant_id IS NOT NULL)=1)
);
CREATE INDEX IF NOT EXISTS ledger_customer ON ledger(user_id,id);
CREATE INDEX IF NOT EXISTS ledger_business ON ledger(business_id,id);
CREATE TABLE IF NOT EXISTS login_attempts (
 identity TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
