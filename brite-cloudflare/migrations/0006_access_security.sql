CREATE TABLE IF NOT EXISTS volunteer_access(email TEXT PRIMARY KEY COLLATE NOCASE,status TEXT NOT NULL CHECK(status IN('pending','approved','rejected','removed','blacklisted')),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,decided_by TEXT);
CREATE TABLE IF NOT EXISTS safety_settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL CHECK(enabled IN(0,1)));
INSERT OR IGNORE INTO safety_settings(id,enabled) VALUES(1,1);
CREATE TABLE IF NOT EXISTS abuse_windows(kind TEXT NOT NULL,subject TEXT NOT NULL,window TEXT NOT NULL,requests INTEGER NOT NULL CHECK(requests>=0),PRIMARY KEY(kind,subject,window));
CREATE TABLE IF NOT EXISTS model_monthly_usage(month TEXT PRIMARY KEY,requests INTEGER NOT NULL,input_chars INTEGER NOT NULL,output_token_allowance INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS model_usage(turn_id TEXT PRIMARY KEY REFERENCES turns(id),email TEXT NOT NULL,scenario_id TEXT NOT NULL,model_id TEXT NOT NULL,input_chars INTEGER NOT NULL,output_token_allowance INTEGER NOT NULL,output_chars INTEGER NOT NULL DEFAULT 0);
