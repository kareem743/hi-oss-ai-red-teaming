CREATE TABLE IF NOT EXISTS brite_workos_flows(state_hash TEXT PRIMARY KEY,verifier_hash TEXT NOT NULL,expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS brite_workos_flow_expiry ON brite_workos_flows(expires_at);
CREATE TABLE IF NOT EXISTS brite_workos_sessions(token_hash TEXT PRIMARY KEY,email TEXT NOT NULL,workos_user_id TEXT NOT NULL,workos_sid TEXT,expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS brite_workos_session_expiry ON brite_workos_sessions(expires_at);
CREATE INDEX IF NOT EXISTS brite_workos_session_email ON brite_workos_sessions(email);
CREATE TABLE IF NOT EXISTS brite_workos_rate(subject TEXT NOT NULL,window INTEGER NOT NULL,requests INTEGER NOT NULL,PRIMARY KEY(subject,window));
