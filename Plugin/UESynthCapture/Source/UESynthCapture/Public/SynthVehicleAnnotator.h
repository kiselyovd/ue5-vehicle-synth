#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "SynthCOCOExporter.h"
#include "SynthVehicleAnnotator.generated.h"

class USkeletalMeshComponent;
class UCameraComponent;

UCLASS(ClassGroup=(UESynth), meta=(BlueprintSpawnableComponent))
class UESYNTHCAPTURE_API USynthVehicleAnnotator : public UActorComponent
{
    GENERATED_BODY()

public:
    USynthVehicleAnnotator();

    /** Map of 24 schema indices -> socket names on the owning skeletal mesh. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "UESynth")
    TMap<FString, FName> SocketBySchemaName;

    /**
     * Optional: explicit actor-local keypoint positions (cm, x=fwd y=right z=up).
     * Takes precedence over SocketBySchemaName per entry. Designed for composite
     * static-mesh vehicles (e.g. City Sample world cars) that have no skeletal mesh.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "UESynth")
    TMap<FString, FVector> LocalPointBySchemaName;

    /**
     * Capture the 24 keypoints projected through CameraComp for one frame.
     * Returns 24 entries; each Visibility is set per occlusion test:
     *   0 = socket missing or fully off-screen / behind camera
     *   1 = on-screen but occluded by another mesh
     *   2 = visible
     */
    UFUNCTION(BlueprintCallable, Category = "UESynth")
    TArray<FCapturedKeypoint> CapturePoints(UCameraComponent* CameraComp, int32 ImageWidth, int32 ImageHeight) const;

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

    USkeletalMeshComponent* GetMesh() const;
};
