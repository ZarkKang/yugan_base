-- 初始化数据库脚本
-- 运行前请确保已创建数据库: CREATE DATABASE drone_db;

-- 创建扩展（如果需要UUID功能）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==================== 用户表 ====================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'operator',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ==================== SKU表 ====================
CREATE TABLE IF NOT EXISTS skus (
    id SERIAL PRIMARY KEY,
    sku_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    unit VARCHAR(20) DEFAULT '个',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_skus_sku_code ON skus(sku_code);
CREATE INDEX IF NOT EXISTS idx_skus_category ON skus(category);

-- ==================== 无人机表 ====================
CREATE TYPE drone_status AS ENUM ('idle', 'flying', 'maintenance', 'retired');

CREATE TABLE IF NOT EXISTS drones (
    id SERIAL PRIMARY KEY,
    drone_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    model VARCHAR(100),
    manufacturer VARCHAR(100),
    status drone_status DEFAULT 'idle',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    altitude DOUBLE PRECISION,
    max_speed DOUBLE PRECISION,
    max_altitude DOUBLE PRECISION,
    flight_duration INTEGER,
    sku_id INTEGER UNIQUE REFERENCES skus(id),
    owner_id INTEGER REFERENCES users(id),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_drones_drone_code ON drones(drone_code);
CREATE INDEX IF NOT EXISTS idx_drones_status ON drones(status);
CREATE INDEX IF NOT EXISTS idx_drones_owner ON drones(owner_id);

-- ==================== 视频数据表 ====================
CREATE TABLE IF NOT EXISTS video_data (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT,
    duration DOUBLE PRECISION,
    resolution VARCHAR(20),
    frame_rate DOUBLE PRECISION,
    codec VARCHAR(50),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    altitude DOUBLE PRECISION,
    drone_id INTEGER REFERENCES drones(id),
    captured_at TIMESTAMP WITH TIME ZONE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_video_drone ON video_data(drone_id);
CREATE INDEX IF NOT EXISTS idx_video_captured ON video_data(captured_at);

-- ==================== 图片数据表 ====================
CREATE TABLE IF NOT EXISTS image_data (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT,
    width INTEGER,
    height INTEGER,
    format VARCHAR(20),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    altitude DOUBLE PRECISION,
    drone_id INTEGER REFERENCES drones(id),
    captured_at TIMESTAMP WITH TIME ZONE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_image_drone ON image_data(drone_id);
CREATE INDEX IF NOT EXISTS idx_image_captured ON image_data(captured_at);

-- ==================== RFID数据表 ====================
CREATE TABLE IF NOT EXISTS rfid_data (
    id SERIAL PRIMARY KEY,
    rfid_tag VARCHAR(100) UNIQUE NOT NULL,
    tag_type VARCHAR(50),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    altitude DOUBLE PRECISION,
    signal_strength DOUBLE PRECISION,
    drone_id INTEGER REFERENCES drones(id),
    detected_at TIMESTAMP WITH TIME ZONE,
    description TEXT,
    is_valid BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rfid_tag ON rfid_data(rfid_tag);
CREATE INDEX IF NOT EXISTS idx_rfid_drone ON rfid_data(drone_id);
CREATE INDEX IF NOT EXISTS idx_rfid_detected ON rfid_data(detected_at);
