"""
MongoDB configuration for chat system
"""
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, DESCENDING
import os

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("MONGO_DB_NAME", "ai_meeting_assistant")

# Global client instance
mongo_client: AsyncIOMotorClient = None
mongo_db = None


async def connect_to_mongo():
    """Connect to MongoDB on startup"""
    global mongo_client, mongo_db
    
    mongo_client = AsyncIOMotorClient(MONGODB_URL)
    mongo_db = mongo_client[DATABASE_NAME]
    
    # Create indexes for better performance
    await create_indexes()
    
    print(f"[mongo] Connected to MongoDB: {MONGODB_URL}")
    print(f"[mongo] Using database: {DATABASE_NAME}")


async def close_mongo_connection():
    """Close MongoDB connection on shutdown"""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        print("[mongo] Closed MongoDB connection")


async def create_indexes():
    """Create indexes for chat collections"""
    
    # Channels indexes
    await mongo_db.channels.create_indexes([
        IndexModel([("type", ASCENDING)]),
        IndexModel([("created_by", ASCENDING)]),
        IndexModel([("members.user_id", ASCENDING)]),
        IndexModel([("is_archived", ASCENDING)]),
    ])
    
    # Messages indexes
    await mongo_db.messages.create_indexes([
        IndexModel([("channel_id", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("parent_message_id", ASCENDING)]),
        IndexModel([("channel_id", ASCENDING), ("deleted_at", ASCENDING)]),
        # Text search index
        IndexModel([("content", "text")]),
    ])
    
    # Reactions indexes
    await mongo_db.reactions.create_indexes([
        IndexModel([("message_id", ASCENDING)]),
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("message_id", ASCENDING), ("user_id", ASCENDING), ("emoji", ASCENDING)], unique=True),
    ])
    
    # Attachments indexes
    await mongo_db.attachments.create_indexes([
        IndexModel([("message_id", ASCENDING)]),
    ])
    
    # DMs indexes
    await mongo_db.direct_messages.create_indexes([
        IndexModel([("participant_1", ASCENDING), ("participant_2", ASCENDING)], unique=True),
        IndexModel([("channel_id", ASCENDING)]),
    ])
    
    print("[mongo] Created indexes for chat collections")


def get_mongo_db():
    """Get MongoDB database instance"""
    return mongo_db
