# Development Notes

Context about how this tool was built and key design decisions.

## AI-Assisted Development

This project was developed through iterative collaboration with multiple AI large language models (LLMs). The development process involved:

- Initial prototyping based on workflow requirements
- Rapid iteration with AI-generated code
- Extensive real-world testing with photo collections
- Refinement based on actual usage patterns

While the code has been extensively tested with real photo collections, users should review the implementation for their specific needs, particularly around:
- Error handling for edge cases
- File system permissions
- Network security (for pipeline features)

## Original Use Case

The tool was built for a specific workflow:

1. Physical photos and negatives digitized on Mac A (photo and scanning workstation)
2. Metadata corrected on Mac A using this tool
3. Photos transferred to Mac B (Photos library Mac) via local network
4. Automatic import to Apple Photos on Mac B
5. Import confirmation sent back to Mac A

## Design Decisions

### Why HEIC Only?

- Target workflow involved converting archival raw images to HEIC
- HEIC is Apple's preferred format
- Simplified development and testing
- Avoided format conversion complexity

### Why Modify Files Directly?

- Ensures metadata travels with the photo
- No sidecar files to manage or lose
- Works seamlessly with Apple Photos import
- Matches how cameras write metadata

The tradeoff is permanent modification without undo capability.

### Why AI-Powered Filename Parsing?

- Filenames rarely follow consistent patterns
- Local LLM provides intelligent extraction without cloud dependencies
- Database caching means each filename is only parsed once
- Falls back to simple patterns if needed

### Why Web Interface?

- Enables fast keyboard navigation
- Platform-native feel on macOS
- Easy batch processing visualization
- No additional GUI framework dependencies
- Accessible from any browser on the local machine

### Why Python + JavaScript?

- Python: Excellent system integration, ExifTool wrapper
- JavaScript: Responsive UI without page reloads
- Flask: Lightweight bridge between them
- Minimal dependencies compared to full frameworks

### Why SQLite?

- Zero configuration database
- Excellent performance for photo metadata
- Single file for easy backup
- Built into Python standard library
- Supports concurrent access with WAL mode

### Threading Architecture

The application uses multiple thread pools:
- **Metadata workers**: Process photos in parallel during scan
- **Thumbnail workers**: Generate thumbnails concurrently
- **Database queue**: Single writer thread for consistency
- **Pipeline executor**: Dedicated thread for transfers

## Technical Architecture

### Three-Tier Design

1. **Data Layer**
   - SQLite with WAL mode for concurrency
   - ExifTool subprocess for metadata operations
   - File system for photo storage

2. **Application Layer**
   - Flask REST API
   - Business logic in Python
   - Caching for performance
   - Thread pools for parallel operations

3. **Presentation Layer**
   - Single-page application in vanilla JavaScript
   - No framework dependencies
   - Responsive design with CSS Grid
   - Real-time updates via polling

### Key Implementation Details

#### Filename Parser
- Local Mistral-7B model extracts dates and locations from filenames
- Understands varied patterns like "Grandma's 80th birthday Chicago 1995"
- Background processing with "Analyzing..." indicator
- Results cached in database for instant future access
- Pre-fetches upcoming photos for seamless navigation

#### Cache Architecture
- Two-level caching: memory + database
- LRU eviction (removes oldest 20 at limit)
- Persistent thumbnail storage
- Metadata cache for ExifTool calls

#### State Management
- Global `AppState` class for application state
- Database queue for write serialization
- Pipeline state tracking for transfers
- UI state in JavaScript (not persisted)

### Server Architecture

- Waitress WSGI server for production stability
- Thread pool with 8 workers for concurrent requests
- Graceful error handling prevents silent failures
- Port binding errors immediately visible to user

#### Error Handling
- Graceful degradation for missing features
- Detailed logging for debugging
- User-friendly error messages
- Automatic retry for transient failures

## Limitations and Trade-offs

### Current Limitations

1. **Format Support**: HEIC only
   - Simplifies implementation
   - Matches target workflow
   - Could be extended with effort

2. **Platform**: macOS only
   - Uses Apple location services
   - Integrates with Apple Photos
   - Cross-platform would lose key features

3. **No Undo**: Direct file modification
   - Simpler architecture
   - Matches camera behavior
   - Requires backup strategy

4. **Single Directory**: One folder at a time
   - Simplifies workflow
   - Reduces complexity
   - Could recurse with changes

5. **LLM Model**: 4GB download on first use
   - One-time download
   - 4-bit quantized for efficiency
   - Requires ~4GB RAM when running

### Performance Trade-offs

1. **Memory Usage**: Caches improve speed but use RAM
2. **Disk Space**: Thumbnails stored for quick access
3. **CPU Usage**: Parallel processing speeds up but uses cores
4. **Network**: Pipeline requires stable connection

### Security Considerations

1. **Local Processing**
   - All photo processing happens locally
   - No cloud services except Apple Maps geocoding
   - No analytics or telemetry
   - No automatic updates

2. **Pipeline Security**
   - SSH key-based authentication only
   - Local network transfers only
   - AutoAddPolicy for convenience
   - Cleanup after successful transfer

3. **File Safety**
   - Direct modification of originals
   - No automatic backups
   - Database corruption possible if interrupted
   - User responsible for backups


## Acknowledgments

Built with assistance from:
- Anthropic's Claude
- OpenAI's GPT models
- The open source community

Special thanks to:
- Phil Harvey for ExifTool
- Flask and Python communities