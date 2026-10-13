#include "strata/core/state_codec.hpp"

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <vector>

using namespace strata::core;
namespace {
int checks = 0;
void check(bool ok, const char* label) {
    ++checks;
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", label); std::exit(1); }
}

// every bf16 code, widened and coded again
bool every_code_round_trips() {
    std::vector<float> f(65536);
    std::vector<uint8_t> out(65536 * 2);
    std::string error;
    for (uint32_t i = 0; i < 65536; ++i) {
        const uint32_t widened = i << 16;   // bfloat16 is the top half of a float32
        std::memcpy(&f[i], &widened, 4);
    }
    for (uint32_t i = 0; i < 65536; ++i) {
        uint32_t b = 0;
        std::memcpy(&b, &f[i], 4);
        if ((b & 0x7F800000u) == 0x7F800000u && (b & 0x007FFFFFu)) continue;   // widened NaNs differ by payload
        if (!state_encode(&f[i], 1, StateCodec::Bf16, out.data() + i * 2, error)) return false;
        uint16_t back = 0;
        std::memcpy(&back, out.data() + i * 2, 2);
        if (back != (uint16_t) i) return false;
    }
    return true;
}

// the worst relative error over a spread of magnitudes, and the sign/zero/extreme cases
void accuracy() {
    std::vector<float> in;
    in.push_back(0.0f); in.push_back(-0.0f); in.push_back(1.0f); in.push_back(-1.0f);
    in.push_back(0.5f); in.push_back(1.0f / 3.0f); in.push_back(-1.0f / 3.0f);
    in.push_back(std::numeric_limits<float>::min());   // the smallest normal, which is also bf16's smallest normal
    in.push_back(1e-30f); in.push_back(1e-8f); in.push_back(1e-3f); in.push_back(3.14159265f);
    in.push_back(1e6f); in.push_back(1e20f); in.push_back(-1e20f); in.push_back(1e38f);
    uint32_t seed = 12345;
    for (int i = 0; i < 4096; ++i) {
        seed = seed * 1664525u + 1013904223u;
        const float magnitude = (float) std::ldexp(1.0, (int) (seed % 80) - 40);
        seed = seed * 1664525u + 1013904223u;
        in.push_back(((seed % 2000) - 1000) / 1000.0f * magnitude);
    }
    std::vector<uint8_t> coded(in.size() * 2);
    std::vector<float> back(in.size());
    std::string error;
    check(state_encode(in.data(), in.size(), StateCodec::Bf16, coded.data(), error), "encode a spread of magnitudes");
    check(state_decode(coded.data(), in.size(), StateCodec::Bf16, back.data(), error), "decode it again");
    const double bound = 1.0 / 256;   // bfloat16 carries 8 significant bits: round-to-nearest-even is within 2^-8
    double worst = 0;
    for (size_t i = 0; i < in.size(); ++i) {
        const float a = in[i], b = back[i];
        if (a == 0.0f) { check(b == 0.0f, "a zero stays a zero with its sign"); continue; }
        if (std::isfinite(a) && !std::isfinite(b)) { check(std::fabs(a) > 3.3e38f, "only a value past the ceiling inflates"); continue; }
        const double rel = std::fabs((b - a) / a);
        if (rel > worst) worst = rel;
    }
    check(worst <= bound, "the worst relative error is within 2^-8");
    check(std::signbit(back[1]), "negative zero keeps its sign");
}

// bf16 has fp32's exponent, so nothing reaches the ceiling by accident; what it gives up is precision, and below its
// smallest denormal a value becomes a zero of the same sign. No value becomes another value's magnitude.
void underflow() {
    const float values[] = {std::numeric_limits<float>::denorm_min(), 1e-40f, -1e-40f, 1e-39f, -1e-39f,
                            std::numeric_limits<float>::min(), -std::numeric_limits<float>::min()};
    uint8_t coded[sizeof values / sizeof *values * 2];
    float back[sizeof values / sizeof *values];
    std::string error;
    check(state_encode(values, 7, StateCodec::Bf16, coded, error) &&
          state_decode(coded, 7, StateCodec::Bf16, back, error), "the subnormal range converts");
    const double step = std::ldexp(1.0, -133);       // one bf16 denormal step
    for (size_t i = 0; i < 7; ++i) {
        check(std::isfinite(back[i]), "nothing in the subnormal range becomes an infinity or a NaN");
        check(std::signbit(back[i]) == std::signbit(values[i]), "and every value keeps its sign");
        // below bf16's smallest normal the grid is fixed, so the error is bounded in absolute terms (half a step),
        // not in relative ones; a value under half a step flushes to a zero of its sign
        check(std::fabs((double) back[i] - (double) values[i]) <= step / 2,
              "a subnormal moves by at most half a bf16 denormal step");
        if (std::fabs(values[i]) < std::ldexp(1.0, -134)) check(back[i] == 0.0f, "under half a step it flushes to zero");
    }
}

void specials() {
    const float inf = std::numeric_limits<float>::infinity();
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float max = std::numeric_limits<float>::max();
    const float values[] = {inf, -inf, nan, max, -max};
    uint8_t coded[sizeof values / sizeof *values * 2];
    float back[sizeof values / sizeof *values];
    std::string error;
    check(state_encode(values, 5, StateCodec::Bf16, coded, error), "encode the extremes");
    check(state_decode(coded, 5, StateCodec::Bf16, back, error), "decode the extremes");
    check(back[0] == inf && back[1] == -inf, "both infinities survive unchanged");
    check(std::isnan(back[2]), "a NaN stays a NaN (a truncated payload would have made it an Inf)");
    check(std::isinf(back[3]) && back[3] > 0 && std::isinf(back[4]) && back[4] < 0,
          "float max rounds to the infinity, which is what round-to-nearest-even means there");
}
} // namespace

int main() {
    std::string error;

    // sizes
    check(state_codec_size(0, StateCodec::Fp32) == 0, "fp32: no bytes is no bytes");
    check(state_codec_size(118063152, StateCodec::Fp32) == 118063152, "fp32 is the identity");
    check(state_codec_size(118063152, StateCodec::Bf16) == 59031576, "bf16 is half");
    check(state_codec_fp32_bytes(59031576, StateCodec::Bf16) == 118063152, "and the inverse finds the fp32 bytes back");
    check(state_codec_fp32_bytes(118063152, StateCodec::Fp32) == 118063152, "fp32 inverse is the identity");
    check(state_codec_fp32_bytes(SIZE_MAX, StateCodec::Bf16) == 0, "a size that would overflow is refused");

    // names and file codes
    StateCodec codec = StateCodec::Bf16;
    check(state_codec_by_name("fp32", codec) && codec == StateCodec::Fp32, "the option name fp32");
    check(state_codec_by_name("BF16", codec) && codec == StateCodec::Bf16, "the option name is case-insensitive");
    check(state_codec_by_name("bfloat16", codec) && codec == StateCodec::Bf16, "the long name");
    check(!state_codec_by_name("", codec), "an empty name is refused");
    check(!state_codec_by_name("int8", codec), "a codec this build does not have is refused, not defaulted");
    check(!state_codec_by_name("fp32x", codec), "a name with trailing text is refused");
    check(std::strcmp(state_codec_name(StateCodec::Fp32), "fp32") == 0, "the name round-trips");
    check(state_codec_by_code(0, codec) && codec == StateCodec::Fp32, "file code 0 is fp32");
    check(state_codec_by_code(1, codec) && codec == StateCodec::Bf16, "file code 1 is bf16");
    check(!state_codec_by_code(2, codec), "an unknown file code is refused");
    check(!state_codec_by_code(256, codec), "a code that is not a byte is refused");

    // fp32 is today's bytes
    {
        const std::vector<float> in{1.0f / 3.0f, -2.5e-7f, 1e30f, 0.0f, -0.0f};
        std::vector<uint8_t> coded(in.size() * 4), today(in.size() * 4);
        std::vector<float> back(in.size());
        check(state_encode(in.data(), in.size(), StateCodec::Fp32, coded.data(), error), "fp32 encode");
        std::memcpy(today.data(), in.data(), in.size() * 4);
        check(coded == today, "fp32 encode writes the bytes the state already has");
        check(state_decode(coded.data(), in.size(), StateCodec::Fp32, back.data(), error), "fp32 decode");
        check(back == in, "fp32 round trip is bit-exact");
    }

    // refusals
    check(state_encode(nullptr, 0, StateCodec::Bf16, nullptr, error), "nothing to convert is not a failure");
    check(!state_encode(nullptr, 4, StateCodec::Bf16, nullptr, error) && !error.empty(),
          "a missing array with values to convert fails and says why");
    check(!state_decode(nullptr, 4, StateCodec::Bf16, nullptr, error), "the same on the way back");

    check(every_code_round_trips(), "every bf16 code widens and codes back to itself");
    accuracy();
    underflow();
    specials();

    std::printf("state_codec_test: %d checks passed\n", checks);
}