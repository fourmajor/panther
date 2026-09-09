FROM ubuntu:24.04@sha256:224a1869083a311ef3f13648a154ba79832fbef6364d31493642ca03082da254 AS build
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git cmake g++ make
# Reviewed upstream whisper.cpp v1.8.3. No game files or models enter the image.
RUN git init /src && cd /src && git remote add origin https://github.com/ggml-org/whisper.cpp.git \
    && git fetch --depth 1 origin 2eeeba56e9edd762b4b38467bab96c2517163158 \
    && git checkout --detach FETCH_HEAD \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
       -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DWHISPER_CURL=OFF -DWHISPER_BUILD_TESTS=OFF \
    && cmake --build build --target whisper-cli -j 2
FROM ubuntu:24.04@sha256:224a1869083a311ef3f13648a154ba79832fbef6364d31493642ca03082da254
COPY --from=build /src/build/bin/whisper-cli /usr/local/bin/whisper-cli
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["/usr/local/bin/whisper-cli"]
