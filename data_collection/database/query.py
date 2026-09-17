from psycopg import sql

ddls = {
    "five_mins_bars_parent": sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS five_mins_bars (
            symbol VARCHAR(10) NOT NULL,
            timestamp BIGINT NOT NULL,
            open NUMERIC(16, 4),
            high NUMERIC(16, 4),
            low NUMERIC(16, 4),
            close NUMERIC(16, 4),
            volume BIGINT,
            bar_count NUMERIC(16,4),
            wap NUMERIC(16,4),
            PRIMARY KEY (symbol, timestamp)
        ) PARTITION BY RANGE (timestamp);
        """
    ),
    "five_mins_bars_partition": sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS {table_name} PARTITION OF five_mins_bars
        FOR VALUES FROM ({start_timestamp}) TO ({end_timestamp});
        """
    ),
    "scanner_result": sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS scanner_result (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            symbol VARCHAR(10) NOT NULL,
            date DATE NOT NULL,
            timestamp BIGINT NOT NULL,
            scanner VARCHAR(100) NOT NULL,
            UNIQUE (symbol, timestamp)
        );
        """
    ),
    "strategy_job": sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS strategy_job (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            symbol VARCHAR(10) NOT NULL,
            created_date DATE NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            UNIQUE (name, symbol, created_date)
        );
        """
    ),
}

dmls = {
    "five_mins_bars": sql.SQL(
        """
        INSERT INTO five_mins_bars
        (symbol, \"timestamp\", open, high, low, close, volume, bar_count, wap)
        VALUES
        (%(symbol)s, %(timestamp)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(bar_count)s, %(wap)s);
        """,
    ),
    "scanner_result": sql.SQL(
        """
        INSERT INTO scanner_result
        (symbol, \"date\", \"timestamp\", scanner, strategy)
        VALUES
        (%(symbol)s,%(date)s, %(timestamp)s, %(scanner)s, %(strategy)s)
        """,
    ),
}

dqls = {
    "scanner_result": sql.SQL(
        """
        SELECT DISTINCT ON (symbol, scanner, strategy) * FROM daily_scanner_result;
        """
    )
}
