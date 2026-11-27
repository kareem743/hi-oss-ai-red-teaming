CREATE TABLE IF NOT EXISTS model_daily_usage (email TEXT NOT NULL REFERENCES users(email),day TEXT NOT NULL,requests INTEGER NOT NULL CHECK(requests>=0),PRIMARY KEY(email,day));
