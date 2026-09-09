/* Native microphone producer + bounded single-producer/single-consumer queue.
 * The audio callback never allocates, locks, logs, writes files, or invokes Python.
 * All conversion, durability, and journal I/O happen on the consumer thread.
 */
#include <portaudio.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define SLOTS 128u
#define MAX_FRAMES 8192u
enum { INPUT_LOSS=1, CLOCK_GAP, QUEUE_FULL, BAD_BUFFER, DISK_ERROR, STALLED, DEVICE_ERROR };
typedef struct {
    unsigned long frames;
    double adc;
    unsigned char *bytes;
} Packet;
typedef struct {
    Packet slots[SLOTS];
    unsigned char *memory;
    atomic_uint head, tail;
    atomic_int error, completed;
    unsigned channels, rate, high_water;
    uint64_t accepted, limit, callbacks;
    double first_adc, next_adc, max_gap;
} Capture;
typedef struct {
    int fd, journal;
    unsigned index, rate, channels;
    uint64_t total, part_frames, chunk_frames;
    double first_adc, part_start, last_adc, last_flush;
} Writer;
static volatile sig_atomic_t stopping = 0;
static void stop_signal(int unused) { (void)unused; stopping = 1; }
static double monotonic_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void fail(Capture *c, int code) {
    int expected = 0;
    atomic_compare_exchange_strong(&c->error, &expected, code);
}
static int receive(const void *input, void *output, unsigned long frames,
                   const PaStreamCallbackTimeInfo *timing,
                   PaStreamCallbackFlags flags, void *user) {
    (void)output;
    Capture *c = user;
    if (atomic_load(&c->error)) return paAbort;
    if (flags & (paInputOverflow | paInputUnderflow)) { fail(c, INPUT_LOSS); return paAbort; }
    if (!input || !frames || frames > MAX_FRAMES || !isfinite(timing->inputBufferAdcTime)) {
        fail(c, BAD_BUFFER); return paAbort;
    }
    double adc = timing->inputBufferAdcTime;
    if (c->callbacks) {
        double gap = fabs(adc - c->next_adc);
        if (gap > c->max_gap) c->max_gap = gap;
        /* Two samples or 100 us allows timestamp rounding, not whole missing buffers. */
        if (gap > fmax(2.0 / c->rate, 0.0001)) { fail(c, CLOCK_GAP); return paAbort; }
    } else c->first_adc = adc;
    c->next_adc = adc + (double)frames / c->rate;
    if (c->limit && frames > c->limit - c->accepted) frames = c->limit - c->accepted;
    unsigned head = atomic_load_explicit(&c->head, memory_order_relaxed);
    unsigned queued = head - atomic_load_explicit(&c->tail, memory_order_acquire);
    if (queued >= SLOTS) { fail(c, QUEUE_FULL); return paAbort; }
    Packet *p = &c->slots[head % SLOTS];
    p->frames = frames;
    p->adc = adc;
    memcpy(p->bytes, input, frames * c->channels * 3);
    c->accepted += frames;
    c->callbacks++;
    if (queued + 1 > c->high_water) c->high_water = queued + 1;
    atomic_store_explicit(&c->head, head + 1, memory_order_release);
    if (c->limit && c->accepted == c->limit) {
        atomic_store(&c->completed, 1); return paComplete;
    }
    return paContinue;
}
static int write_all(int fd, const void *data, size_t size) {
    const unsigned char *p = data;
    while (size) {
        ssize_t n = write(fd, p, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n; size -= (size_t)n;
    }
    return 0;
}
static void le16(unsigned char *p, unsigned v) { p[0]=v; p[1]=v>>8; }
static void le32(unsigned char *p, uint32_t v) { for (int i=0;i<4;i++) p[i]=v>>(8*i); }
static int wav_header(Writer *w, int final) {
    unsigned char h[44] = {0};
    uint64_t size = w->part_frames * w->channels * 3;
    if (size > UINT32_MAX - 37) return -1;
    memcpy(h,"RIFF",4); le32(h+4,(uint32_t)size+36+(final?(size&1):0)); memcpy(h+8,"WAVEfmt ",8);
    le32(h+16,16); le16(h+20,1); le16(h+22,w->channels); le32(h+24,w->rate);
    le32(h+28,w->rate*w->channels*3); le16(h+32,w->channels*3); le16(h+34,24);
    memcpy(h+36,"data",4); le32(h+40,(uint32_t)size);
    ssize_t n;
    do { n = pwrite(w->fd,h,sizeof h,0); } while (n < 0 && errno == EINTR);
    return n == sizeof h ? 0 : -1;
}
static int durable(int fd) {
    if (fsync(fd)) return -1;
#ifdef __APPLE__
    if (fcntl(fd,F_FULLFSYNC)) return -1;
#endif
    return 0;
}
static int close_part(Writer *w) {
    if (w->fd < 0) return 0;
    if ((w->part_frames*w->channels*3)&1) {
        unsigned char pad=0;
        if (write_all(w->fd,&pad,1)) return -1;
    }
    if (wav_header(w,1) || durable(w->fd)) return -1;
    if (close(w->fd)) { w->fd=-1; return -1; }
    w->fd=-1;
    int directory = open("capture-pcm",O_RDONLY);
    if (directory < 0) return -1;
    int result = fsync(directory); close(directory);
    if (result) return -1;
    char row[180];
    int len=snprintf(row,sizeof row,"part-%04u.wav,%.9f,%.9f\n",w->index,w->part_start,w->last_adc);
    if (len < 0 || len >= (int)sizeof row || write_all(w->journal,row,len) || durable(w->journal)) return -1;
    w->index++; w->part_frames=0;
    return 0;
}
static int consume(Writer *w, const Packet *p) {
    uint64_t offset=0;
    while (offset < p->frames) {
        if (w->fd < 0) {
            if (w->index > 9999) return -1;
            char name[80]; snprintf(name,sizeof name,"capture-pcm/part-%04u.wav",w->index);
            w->fd=open(name,O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
            if (w->fd < 0 || wav_header(w,0) || lseek(w->fd,44,SEEK_SET)<0) return -1;
            w->part_start=p->adc-w->first_adc+(double)offset/w->rate;
        }
        uint64_t count=p->frames-offset, room=w->chunk_frames-w->part_frames;
        if (count>room) count=room;
        if (write_all(w->fd,p->bytes+offset*w->channels*3,count*w->channels*3)) return -1;
        w->part_frames+=count; w->total+=count; offset+=count;
        w->last_adc=p->adc-w->first_adc+(double)offset/w->rate;
        /* A valid active-file header is maintained for recovery after an abrupt stop. */
        if (wav_header(w,0)) return -1;
        if (w->part_frames==w->chunk_frames) {
            if (close_part(w)) return -1;
        } else if (monotonic_now()-w->last_flush>=1) {
            if (durable(w->fd)) return -1;
            w->last_flush=monotonic_now();
        }
    }
    return 0;
}
static int drain(Capture *c, Writer *w) {
    unsigned tail=atomic_load_explicit(&c->tail,memory_order_relaxed);
    while (tail != atomic_load_explicit(&c->head,memory_order_acquire)) {
        if (!w->total) w->first_adc=c->slots[tail%SLOTS].adc;
        if (consume(w,&c->slots[tail%SLOTS])) { fail(c,DISK_ERROR); return -1; }
        atomic_store_explicit(&c->tail,++tail,memory_order_release);
    }
    return 0;
}
static int control_requested(void) {
    fd_set fds; FD_ZERO(&fds); FD_SET(STDIN_FILENO,&fds);
    struct timeval timeout={0,0};
    int n=select(STDIN_FILENO+1,&fds,NULL,NULL,&timeout);
    if (n>0) { char b; (void)read(STDIN_FILENO,&b,1); return 1; }
    return stopping;
}
static int report(Capture *c, Writer *w, int synthetic) {
    int fd=open("capture-health.json",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    if (fd<0) return -1;
    char data[1024];
    int len=snprintf(data,sizeof data,
        "{\"schemaVersion\":1,\"backend\":\"%s\",\"sampleRate\":%u,\"channels\":%u,"
        "\"capturedFrames\":%llu,\"acceptedFrames\":%llu,\"callbacks\":%llu,"
        "\"deviceElapsedSeconds\":%.9f,\"maxTimestampGapSeconds\":%.9f,"
        "\"queueHighWater\":%u,\"queueCapacity\":%u,\"errorCode\":%d,\"cleanStop\":%s}\n",
        synthetic?"synthetic-native":"portaudio-coreaudio",c->rate,c->channels,
        (unsigned long long)w->total,(unsigned long long)c->accepted,(unsigned long long)c->callbacks,
        w->last_adc,c->max_gap,c->high_water,SLOTS,atomic_load(&c->error),
        atomic_load(&c->error)?"false":"true");
    int result=(len<0 || len>=(int)sizeof data || write_all(fd,data,len) || durable(fd));
    close(fd);
    return result ? -1 : 0;
}
int main(int argc, char **argv) {
    if (argc!=2 && argc!=5) { fprintf(stderr,"Usage: capture --list | DEVICE FOLDER SECONDS CHUNK_SECONDS\n"); return 2; }
    int synthetic=argc==5 && !strncmp(argv[1],"--synthetic",11);
    int listed=argc==2 && !strcmp(argv[1],"--list");
    if (argc==2 && !listed) return 2;
    PaStream *stream=NULL;
    PaDeviceIndex device=paNoDevice;
    Capture c={0};
    if (!synthetic) {
        PaError error=Pa_Initialize();
        if (error!=paNoError) { fprintf(stderr,"PortAudio: %s\n",Pa_GetErrorText(error)); return 2; }
        int matches=0, n=Pa_GetDeviceCount();
        for (int i=0;i<n;i++) {
            const PaDeviceInfo *info=Pa_GetDeviceInfo(i);
            const PaHostApiInfo *host=Pa_GetHostApiInfo(info->hostApi);
            if (host->type!=paCoreAudio || info->maxInputChannels<1) continue;
            if (listed) printf("%s\n",info->name);
            else if (!strcmp(info->name,argv[1])) { device=i; matches++; }
        }
        if (listed) { Pa_Terminate(); return n<0?2:0; }
        if (matches!=1) { fprintf(stderr,"Expected one exact Core Audio input device; found %d. No fallback.\n",matches); Pa_Terminate(); return 2; }
        const PaDeviceInfo *info=Pa_GetDeviceInfo(device);
        c.rate=(unsigned)llround(info->defaultSampleRate); c.channels=info->maxInputChannels;
    } else { c.rate=48000; c.channels=1; }
    char *end=NULL;
    double seconds=strtod(argv[3],&end);
    if (*end || !isfinite(seconds) || seconds<0 || seconds>43200) return 2;
    double chunk=strtod(argv[4],&end);
    if (*end || !isfinite(chunk) || chunk<0.1 || chunk>600 || c.rate<8000 || c.rate>384000 || c.channels<1 || c.channels>32) return 2;
    if (chunk*c.rate*c.channels*3 > UINT32_MAX-36) { fprintf(stderr,"Chunk exceeds WAV capacity.\n"); return 2; }
    c.limit=(uint64_t)llround(seconds*c.rate);
    c.memory=calloc(SLOTS,MAX_FRAMES*c.channels*3);
    if (!c.memory || !atomic_is_lock_free(&c.head) || !atomic_is_lock_free(&c.error)) return 2;
    /* Fault in queue pages before entering the real-time callback. */
    for (size_t i=0;i<(size_t)SLOTS*MAX_FRAMES*c.channels*3;i+=4096) ((volatile unsigned char *)c.memory)[i]=0;
    for (unsigned i=0;i<SLOTS;i++) c.slots[i].bytes=c.memory+(size_t)i*MAX_FRAMES*c.channels*3;
    umask(0077);
    if (chdir(argv[2])) { perror("Capture directory"); return 2; }
    Writer w={.fd=-1,.journal=-1,.rate=c.rate,.channels=c.channels,.chunk_frames=(uint64_t)llround(chunk*c.rate)};
    w.journal=open("segments.csv",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    if (w.journal<0) { perror("Capture journal"); return 2; }
    signal(SIGINT,stop_signal); signal(SIGTERM,stop_signal); signal(SIGHUP,stop_signal);
    if (!synthetic) {
        const PaDeviceInfo *info=Pa_GetDeviceInfo(device);
        PaStreamParameters input={.device=device,.channelCount=(int)c.channels,.sampleFormat=paInt24,
            .suggestedLatency=fmax(0.1,info->defaultHighInputLatency),.hostApiSpecificStreamInfo=NULL};
        PaError error=Pa_OpenStream(&stream,&input,NULL,c.rate,paFramesPerBufferUnspecified,paDitherOff,receive,&c);
        if (error==paNoError && fabs(Pa_GetStreamInfo(stream)->sampleRate-c.rate)>0.01) error=paInvalidSampleRate;
        if (error==paNoError) error=Pa_StartStream(stream);
        if (error!=paNoError) { fprintf(stderr,"Capture: %s\n",Pa_GetErrorText(error)); fail(&c,DEVICE_ERROR); }
    }
    double began=monotonic_now(), last_progress=began;
    uint64_t last_total=0, synthetic_frame=0;
    unsigned char tone[512*3];
    while (!atomic_load(&c.error) && !stopping) {
        if (control_requested()) break;
        if (synthetic && !atomic_load(&c.completed) && monotonic_now()-began >= (double)synthetic_frame/c.rate) {
            for (unsigned i=0;i<512;i++) {
                unsigned value=(synthetic_frame+i)%8388608;
                tone[i*3]=value; tone[i*3+1]=value>>8; tone[i*3+2]=value>>16;
            }
            PaStreamCallbackTimeInfo t={.inputBufferAdcTime=100+(double)synthetic_frame/c.rate};
            if (!strcmp(argv[1],"--synthetic-gap") && synthetic_frame>=48000) t.inputBufferAdcTime+=512.0/c.rate;
            PaStreamCallbackFlags flags=(!strcmp(argv[1],"--synthetic-overflow") && synthetic_frame>=48000)?paInputOverflow:0;
            receive(tone,NULL,512,&t,flags,&c); synthetic_frame+=512;
        }
        if (strcmp(argv[1],"--synthetic-queue-full") && drain(&c,&w)) break;
        if (w.total!=last_total) { last_total=w.total; last_progress=monotonic_now(); }
        if (atomic_load(&c.completed)) break;
        if ((!synthetic && (!stream || Pa_IsStreamActive(stream)<=0)) || monotonic_now()-last_progress>5) { fail(&c,STALLED); break; }
        usleep(1000);
    }
    if (stream) { Pa_StopStream(stream); Pa_CloseStream(stream); }
    if (!synthetic) Pa_Terminate();
    if (atomic_load(&c.error)!=DISK_ERROR) (void)drain(&c,&w);
    if (close_part(&w)) fail(&c,DISK_ERROR);
    if (w.fd>=0) close(w.fd);
    close(w.journal);
    if (!w.total) fail(&c,DEVICE_ERROR);
    if (report(&c,&w,synthetic)) { fprintf(stderr,"Could not persist capture health.\n"); fail(&c,DISK_ERROR); }
    int error=atomic_load(&c.error);
    fprintf(stderr,"Capture ended: frames=%llu, rate=%u, error=%d. No missing samples were synthesized.\n",(unsigned long long)w.total,c.rate,error);
    free(c.memory);
    return error?1:0;
}
