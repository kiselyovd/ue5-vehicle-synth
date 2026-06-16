#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SynthRoadQuery.generated.h"

/** One sampled vertex of a baked ZoneGraph lane polyline. */
USTRUCT(BlueprintType)
struct FSynthLaneSample
{
    GENERATED_BODY()

    /** World position of the lane point (cm). */
    UPROPERTY(BlueprintReadOnly, Category = "UESynth")
    FVector Position = FVector::ZeroVector;

    /** Unit travel direction along the lane at this point. */
    UPROPERTY(BlueprintReadOnly, Category = "UESynth")
    FVector Direction = FVector::ForwardVector;

    /** Lane width (cm); lets callers drop narrow pedestrian lanes. */
    UPROPERTY(BlueprintReadOnly, Category = "UESynth")
    float Width = 0.0f;
};

/** Editor/runtime road geometry queries for synthetic capture placement. */
UCLASS()
class UESYNTHCAPTURE_API USynthRoadQuery : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * Query baked ZoneGraph lanes near Center within RadiusCm (XY distance).
     * Returns one FSynthLaneSample per lane polyline vertex in range: world
     * position, unit travel direction (from the lane tangent vectors), and lane
     * width. Returns empty when no ZoneGraph subsystem/data is available, in
     * which case the caller falls back to road-surface raycasting in Python.
     */
    UFUNCTION(BlueprintCallable, Category = "UESynth", meta = (WorldContext = "WorldContextObject"))
    static TArray<FSynthLaneSample> QueryZoneGraphLanes(UObject* WorldContextObject, FVector Center, float RadiusCm);
};
